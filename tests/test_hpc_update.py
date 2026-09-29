"""deploy/scripts/hpc-update.sh against a real git remote and a fake `apptainer`.

The fake pulls `docker://<repo>:<tag>` only when FAKE_ROOT/available-<tag> exists.
The fake venv python appends its arguments to FAKE_ROOT/pip.log.
"""

import fcntl
import os
import subprocess
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "deploy" / "scripts" / "hpc-update.sh"

FAKE_APPTAINER = r"""#!/usr/bin/env bash
echo "$*" >> "$FAKE_ROOT/apptainer.log"
[[ "$1" == pull && "$2" == --disable-cache ]] || exit 2
tag="${4##*:}"
[[ -f "$FAKE_ROOT/available-$tag" ]] || exit 1
echo "image $tag" > "$3"
"""

FAKE_PYTHON = r"""#!/usr/bin/env bash
echo "$*" >> "$FAKE_ROOT/pip.log"
"""

GIT_ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.org",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.org",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
}


def _git(cwd, *args):
    return subprocess.run(
        ["git", *args], cwd=cwd, env={**os.environ, **GIT_ENV}, check=True, capture_output=True, text=True
    ).stdout.strip()


def _executable(path, text):
    path.write_text(text)
    path.chmod(0o755)


class Hpc:
    def __init__(self, tmp_path):
        self.upstream = tmp_path / "upstream"
        self.upstream.mkdir()
        _git(self.upstream, "init", "-q", "-b", "master")
        (self.upstream / "requirements.txt").write_text("httpx\n")
        (self.upstream / "requirements-web.txt").write_text("fastapi\n")
        self.commit("initial")
        self.repo = tmp_path / "repo"
        _git(tmp_path, "clone", "-q", str(self.upstream), str(self.repo))

        self.fake = tmp_path / "fake"
        self.fake.mkdir()
        _executable(self.fake / "apptainer", FAKE_APPTAINER)
        self.venv = tmp_path / "venv"
        (self.venv / "bin").mkdir(parents=True)
        _executable(self.venv / "bin" / "python", FAKE_PYTHON)
        self.sif_dir = tmp_path / "sif"
        self.log = tmp_path / "hpc-update.log"
        self.lock = tmp_path / "hpc-update.lock"
        self.env = {
            **os.environ,
            **GIT_ENV,
            "FAKE_ROOT": str(self.fake),
            "APPTAINER": str(self.fake / "apptainer"),
            "GAA_REPO": str(self.repo),
            "GAA_VENV": str(self.venv),
            "GAA_SIF_DIR": str(self.sif_dir),
            "GAA_HPC_UPDATE_LOG": str(self.log),
            "GAA_HPC_UPDATE_LOCK": str(self.lock),
        }

    def commit(self, message, files=None):
        for name, text in (files or {}).items():
            (self.upstream / name).write_text(text)
        _git(self.upstream, "add", "-A")
        _git(self.upstream, "commit", "-q", "--allow-empty", "-m", message)
        return _git(self.upstream, "rev-parse", "HEAD")

    def publish(self, sha):
        (self.fake / f"available-sha-{sha[:7]}").write_text("")

    def run(self, **env):
        return subprocess.run(["bash", str(SCRIPT)], env={**self.env, **env}, capture_output=True, text=True)

    def head(self):
        return _git(self.repo, "rev-parse", "HEAD")

    def calls(self, name):
        path = self.fake / name
        return path.read_text().splitlines() if path.exists() else []

    def current(self):
        return os.readlink(self.sif_dir / "worker-current.sif")


@pytest.fixture
def hpc(tmp_path):
    return Hpc(tmp_path)


def test_waits_for_the_image_before_moving_code(hpc):
    old = hpc.head()
    hpc.publish(old)
    assert hpc.run().returncode == 0
    new = hpc.commit("second")

    result = hpc.run()

    assert result.returncode == 0
    assert hpc.head() == old
    assert hpc.current() == f"worker-sha-{old[:7]}.sif"
    assert f"waiting: ghcr.io/cadsaltz/gene-autoannotator-worker:sha-{new[:7]}" in hpc.log.read_text()
    assert not list(hpc.sif_dir.glob(".worker-*"))


def test_moves_code_and_sif_together_then_is_a_noop(hpc):
    new = hpc.commit("second")
    hpc.publish(new)

    assert hpc.run().returncode == 0
    assert hpc.head() == new
    assert hpc.current() == f"worker-sha-{new[:7]}.sif"
    assert (hpc.sif_dir / f"worker-sha-{new[:7]}.sif").read_text() == f"image sha-{new[:7]}\n"
    assert len(hpc.calls("pip.log")) == 1
    assert "--requirement=requirements.txt --requirement=requirements-web.txt" in hpc.calls("pip.log")[0]

    assert hpc.run().returncode == 0
    assert len(hpc.calls("apptainer.log")) == 1
    assert len(hpc.calls("pip.log")) == 1
    assert hpc.log.read_text().splitlines()[-1].endswith(f"up to date at {new[:7]}")


def test_reinstalls_only_when_requirements_change(hpc):
    hpc.publish(hpc.head())
    hpc.run()
    hpc.publish(hpc.commit("docs only", {"README.md": "x\n"}))
    hpc.run()
    assert len(hpc.calls("pip.log")) == 1

    hpc.publish(hpc.commit("bump", {"requirements.txt": "httpx==0.28.1\n"}))
    assert hpc.run().returncode == 0
    assert len(hpc.calls("pip.log")) == 2


def test_prunes_old_sifs_only_after_the_grace_period(hpc):
    hpc.sif_dir.mkdir()
    day = 24 * 3600
    now = time.time()
    for name, age in (("a", 5 * day), ("b", 4 * day), ("c", 1 * day)):
        path = hpc.sif_dir / f"worker-sha-{name * 7}.sif"
        path.write_text(name)
        os.utime(path, (now - age, now - age))
    hpc.publish(hpc.head())

    assert hpc.run().returncode == 0

    # new (now), c (1 day), b (4 days; c replaced it 1 day ago), a (b replaced it 4 days ago)
    names = sorted(p.name for p in hpc.sif_dir.glob("worker-sha-*.sif"))
    assert f"worker-sha-{'a' * 7}.sif" not in names
    assert f"worker-sha-{'b' * 7}.sif" in names
    assert len(names) == 3


def test_code_only_mode_skips_apptainer(hpc):
    new = hpc.commit("second")

    assert hpc.run(GAA_PULL_SIF="0").returncode == 0

    assert hpc.head() == new
    assert hpc.calls("apptainer.log") == []
    assert not hpc.sif_dir.exists()


def test_diverged_checkout_is_left_alone(hpc):
    hpc.publish(hpc.head())
    (hpc.repo / "local.txt").write_text("x")
    _git(hpc.repo, "add", "local.txt")
    _git(hpc.repo, "commit", "-q", "-m", "local")
    local = hpc.head()
    hpc.commit("remote")

    result = hpc.run()

    assert result.returncode == 1
    assert hpc.head() == local
    assert "has diverged" in hpc.log.read_text()


def test_overlapping_run_exits(hpc):
    with open(hpc.lock, "w") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        result = hpc.run()
    assert result.returncode == 0
    assert "another update is running" in hpc.log.read_text()
    assert hpc.calls("apptainer.log") == []
