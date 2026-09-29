"""deploy/scripts/server-update.sh against a fake `docker` CLI.

State lives in files under FAKE_ROOT: `running` (backend is up), `img-<service>`
(running image id), `new-<service>` (what the next pull fetches), `unhealthy`,
`pull-fails`. Every call is appended to calls.log.
"""

import fcntl
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "deploy" / "scripts" / "server-update.sh"
COMPOSE_DIR = REPO_ROOT / "deploy" / "compose"

FAKE_DOCKER = r"""#!/usr/bin/env bash
R="$FAKE_ROOT"
echo "$*" >> "$R/calls.log"
args="$*"
service="${args##* }"
case "$args" in
  compose*" ps -q --status running backend")
    [[ -f "$R/running" ]] && echo "cid-backend" ;;
  compose*" ps -q "*)
    [[ -f "$R/img-$service" ]] && echo "cid-$service" ;;
  "inspect -f {{.Image}} cid-"*)
    cat "$R/img-${service#cid-}" ;;
  compose*" pull --quiet")
    [[ -f "$R/pull-fails" ]] && exit 1
    for f in "$R"/new-*; do [[ -f "$f" ]] && mv "$f" "$R/pending-${f##*/new-}"; done ;;
  compose*" up -d --quiet-pull")
    for f in "$R"/pending-*; do [[ -f "$f" ]] && mv "$f" "$R/img-${f##*/pending-}"; done ;;
  compose*" exec -T backend "*)
    [[ -f "$R/unhealthy" ]] && exit 1 ;;
esac
exit 0
"""


@pytest.fixture
def stack(tmp_path):
    compose_dir = tmp_path / "compose"
    compose_dir.mkdir()
    shutil.copy(COMPOSE_DIR / "docker-compose.prod.yml", compose_dir / "docker-compose.yml")
    shutil.copy(COMPOSE_DIR / "docker-compose.worker-port.yml", compose_dir / "docker-compose.worker-port.yml")
    (compose_dir / "compose.env").write_text("IMAGE_TAG=prod\nSITE_ADDRESS=example.org\n")
    backend = (COMPOSE_DIR / "backend.prod.env.example").read_text().replace("CHANGE_ME", "filled")
    (compose_dir / "backend.env").write_text(backend)
    frontend = (COMPOSE_DIR / "frontend.prod.env.example").read_text().replace("CHANGE_ME", "filled")
    (compose_dir / "frontend.env").write_text(frontend)

    fake_root = tmp_path / "fake"
    fake_root.mkdir()
    (fake_root / "running").write_text("")
    for service in ("backend", "frontend", "caddy"):
        (fake_root / f"img-{service}").write_text(f"sha256:old-{service}\n")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text(FAKE_DOCKER)
    docker.chmod(docker.stat().st_mode | stat.S_IXUSR)
    return tmp_path, compose_dir, fake_root, bin_dir


def _run(stack, **extra_env):
    tmp_path, compose_dir, fake_root, bin_dir = stack
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "FAKE_ROOT": str(fake_root),
        "GAA_COMPOSE_FILE": str(compose_dir / "docker-compose.yml"),
        "GAA_UPDATE_LOG": str(tmp_path / "update.log"),
        "GAA_UPDATE_LOCK": str(tmp_path / "update.lock"),
        "GAA_HEALTH_TIMEOUT": "2",
        "GAA_HEALTH_INTERVAL": "1",
        **extra_env,
    }
    result = subprocess.run(["bash", str(SCRIPT)], capture_output=True, text=True, env=env, timeout=60)
    log = (tmp_path / "update.log").read_text() if (tmp_path / "update.log").exists() else ""
    calls = (fake_root / "calls.log").read_text() if (fake_root / "calls.log").exists() else ""
    return result, log, calls


def test_no_new_images_logs_one_line_and_does_not_prune(stack):
    result, log, calls = _run(stack)
    assert result.returncode == 0, result.stderr + log
    assert log.strip().endswith("no new images")
    assert len(log.strip().splitlines()) == 1
    assert "-p gaa -f" in calls and "--env-file" in calls
    assert "pull --quiet" in calls and "up -d --quiet-pull" in calls
    assert "image prune" not in calls
    assert "exec -T backend" not in calls


def test_new_images_are_logged_tagged_previous_and_only_dangling_pruned(stack):
    _tmp, _compose_dir, fake_root, _bin = stack
    (fake_root / "new-backend").write_text("sha256:new-backend\n")
    result, log, calls = _run(stack)
    assert result.returncode == 0, result.stderr + log
    assert "backend: sha256:old-backend -> sha256:new-backend" in log
    assert "frontend: sha256" not in log
    assert "tag sha256:old-backend ghcr.io/cadsaltz/gene-autoannotator-backend:previous" in calls
    # the unchanged frontend is tagged too, so :previous is always a matching pair
    assert "tag sha256:old-frontend ghcr.io/cadsaltz/gene-autoannotator-frontend:previous" in calls
    assert "tag sha256:old-caddy" not in calls
    assert "exec -T backend python" in calls
    assert "backend healthy" in log
    assert "image prune -f\n" in calls
    assert "prune -a" not in calls and "prune -af" not in calls
    # previous is tagged before prune removes the now-dangling old image
    assert calls.index("tag sha256:old-backend") < calls.index("image prune -f")


def test_unhealthy_backend_after_update_logs_a_loud_error(stack):
    _tmp, _compose_dir, fake_root, _bin = stack
    (fake_root / "new-backend").write_text("sha256:new-backend\n")
    (fake_root / "unhealthy").write_text("")
    result, log, calls = _run(stack)
    assert result.returncode == 1
    assert "ERROR: backend is not healthy" in log
    assert "sha256:old-backend" in log
    assert "IMAGE_TAG=previous" in log
    assert "update FAILED" not in log


def test_skips_when_the_backend_is_not_running(stack):
    _tmp, _compose_dir, fake_root, _bin = stack
    (fake_root / "running").unlink()
    result, log, calls = _run(stack)
    assert result.returncode == 0
    assert log.strip().endswith("stack not running; skipping")
    assert "pull" not in calls and "up -d" not in calls


def test_all_compose_files_are_passed(stack):
    _tmp, compose_dir, _fake_root, _bin = stack
    files = f"{compose_dir / 'docker-compose.yml'}:{compose_dir / 'docker-compose.worker-port.yml'}"
    result, log, calls = _run(stack, GAA_COMPOSE_FILES=files)
    assert result.returncode == 0, result.stderr + log
    for line in calls.splitlines():
        if line.startswith("compose"):
            assert f"-f {compose_dir / 'docker-compose.yml'} -f {compose_dir / 'docker-compose.worker-port.yml'}" in line
            assert f"--env-file {compose_dir / 'compose.env'}" in line


def test_failed_preflight_leaves_the_stack_alone(stack):
    _tmp, compose_dir, _fake_root, _bin = stack
    env_file = compose_dir / "backend.env"
    env_file.write_text(env_file.read_text().replace("TRUST_FORWARDED_FOR=1", "TRUST_FORWARDED_FOR=0"))
    result, log, calls = _run(stack)
    assert result.returncode == 1
    assert "preflight failed" in log
    assert "backend: INVALID TRUST_FORWARDED_FOR" in log
    assert "filled" not in log
    assert "pull" not in calls and "up -d" not in calls


def test_absolute_backend_env_file_path(stack):
    tmp_path, compose_dir, _fake_root, _bin = stack
    elsewhere = tmp_path / "secrets" / "backend.env"
    elsewhere.parent.mkdir()
    (compose_dir / "backend.env").rename(elsewhere)
    with open(compose_dir / "compose.env", "a") as handle:
        handle.write(f"BACKEND_ENV_FILE={elsewhere}\n")
    result, log, calls = _run(stack)
    assert result.returncode == 0, result.stderr + log
    assert "preflight failed" not in log


def test_failed_pull_is_logged(stack):
    _tmp, _compose_dir, fake_root, _bin = stack
    (fake_root / "pull-fails").write_text("")
    result, log, calls = _run(stack)
    assert result.returncode == 1
    assert "update FAILED" in log
    assert "up -d" not in calls


def test_overlapping_run_exits_quietly(stack):
    tmp_path, _compose_dir, _fake_root, _bin = stack
    with open(tmp_path / "update.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        result, log, calls = _run(stack)
    assert result.returncode == 0
    assert "another update is running" in log
    assert calls == ""


def test_lock_defaults_to_run_lock_or_tmp():
    text = SCRIPT.read_text()
    assert "/run/lock" in text and "/tmp/gaa-update.lock" in text
