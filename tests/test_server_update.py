"""deploy/scripts/server-update.sh against a fake `docker` CLI."""

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

FAKE_DOCKER = """#!/usr/bin/env bash
echo "$*" >> "$FAKE_ROOT/calls.log"
case "$*" in
  *" images --quiet") cat "$FAKE_ROOT/images" 2>/dev/null ;;
  *" pull --quiet") [[ -f "$FAKE_ROOT/pull-fails" ]] && exit 1; [[ -f "$FAKE_ROOT/new-images" ]] && cp "$FAKE_ROOT/new-images" "$FAKE_ROOT/pending" ;;
  *" up -d --quiet-pull") [[ -f "$FAKE_ROOT/pending" ]] && mv "$FAKE_ROOT/pending" "$FAKE_ROOT/images" ;;
esac
exit 0
"""


@pytest.fixture
def stack(tmp_path):
    compose_dir = tmp_path / "compose"
    compose_dir.mkdir()
    shutil.copy(COMPOSE_DIR / "docker-compose.prod.yml", compose_dir / "docker-compose.yml")
    (compose_dir / "compose.env").write_text("IMAGE_TAG=prod\nSITE_ADDRESS=example.org\n")
    backend = (COMPOSE_DIR / "backend.prod.env.example").read_text()
    backend = backend.replace("CHANGE_ME", "filled")
    (compose_dir / "backend.env").write_text(backend)
    frontend = (COMPOSE_DIR / "frontend.prod.env.example").read_text().replace("CHANGE_ME", "filled")
    (compose_dir / "frontend.env").write_text(frontend)

    fake_root = tmp_path / "fake"
    fake_root.mkdir()
    (fake_root / "images").write_text("sha256:old-backend\nsha256:old-frontend\n")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text(FAKE_DOCKER)
    docker.chmod(docker.stat().st_mode | stat.S_IXUSR)
    return tmp_path, compose_dir, fake_root, bin_dir


def _run(stack):
    tmp_path, compose_dir, fake_root, bin_dir = stack
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "FAKE_ROOT": str(fake_root),
        "GAA_COMPOSE_FILE": str(compose_dir / "docker-compose.yml"),
        "GAA_UPDATE_LOG": str(tmp_path / "update.log"),
        "GAA_UPDATE_LOCK": str(tmp_path / "update.lock"),
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


def test_new_images_are_logged_and_only_dangling_images_pruned(stack):
    _tmp, _compose_dir, fake_root, _bin = stack
    (fake_root / "new-images").write_text("sha256:new-backend\nsha256:old-frontend\n")
    result, log, calls = _run(stack)
    assert result.returncode == 0, result.stderr + log
    assert "updated; running images now: sha256:new-backend sha256:old-frontend" in log
    assert "image prune -f\n" in calls
    assert "prune -a" not in calls and "prune -af" not in calls


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
