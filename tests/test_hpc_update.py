"""deploy/scripts/hpc-update.sh against a real git remote and a fake `apptainer`.

The upstream repo carries the real worker-image-key.sh and a stub for each
worker image path. The fake apptainer pulls `docker://<repo>:<tag>` only when
FAKE_ROOT/available-<tag> exists. The fake venv python appends its arguments to
FAKE_ROOT/pip.log.
"""

import fcntl
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "deploy" / "scripts" / "hpc-update.sh"
KEY_SCRIPT = REPO_ROOT / "deploy" / "scripts" / "worker-image-key.sh"

FAKE_APPTAINER = r"""#!/usr/bin/env bash
echo "$* cache=$APPTAINER_CACHEDIR" >> "$FAKE_ROOT/apptainer.log"
if [[ "$1 $2" == "cache clean" ]]; then exit 0; fi
[[ "$1" == pull && "$3" == docker://* ]] || exit 2
tag="${3##*:}"
[[ -f "$FAKE_ROOT/available-$tag" ]] || exit 1
echo "image $tag" > "$2"
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

DAY = 24 * 3600


def _git(cwd, *args):
    return subprocess.run(
        ["git", *args], cwd=cwd, env={**os.environ, **GIT_ENV}, check=True, capture_output=True, text=True
    ).stdout.strip()


def _executable(path, text):
    path.write_text(text)
    path.chmod(0o755)


def _age(path, seconds):
    t = time.time() - seconds
    os.utime(path, (t, t))


class Hpc:
    def __init__(self, tmp_path):
        self.upstream = tmp_path / "upstream"
        self.upstream.mkdir()
        _git(self.upstream, "init", "-q", "-b", "master")
        paths = subprocess.run([str(KEY_SCRIPT), "--paths"], check=True, capture_output=True, text=True)
        for rel in paths.stdout.split():
            target = self.upstream / rel
            if "." in target.name:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(f"{rel}\n")
            else:
                target.mkdir(parents=True, exist_ok=True)
                (target / "stub").write_text(f"{rel}\n")
        (self.upstream / "requirements.txt").write_text("httpx\n")
        (self.upstream / "requirements-web.txt").write_text("fastapi\n")
        key_dest = self.upstream / "deploy" / "scripts" / "worker-image-key.sh"
        key_dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(KEY_SCRIPT, key_dest)
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
            **{k: v for k, v in os.environ.items() if not k.startswith("APPTAINER")},
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

    def key(self, rev="HEAD"):
        return subprocess.run(
            [str(KEY_SCRIPT), rev], cwd=self.upstream, check=True, capture_output=True, text=True
        ).stdout.strip()

    def publish(self, rev="HEAD"):
        key = self.key(rev)
        (self.fake / f"available-src-{key}").write_text("")
        return key

    def sif(self, key):
        return self.sif_dir / f"worker-src-{key}.sif"

    def run(self, **env):
        return subprocess.run(["bash", str(SCRIPT)], env={**self.env, **env}, capture_output=True, text=True)

    def head(self):
        return _git(self.repo, "rev-parse", "HEAD")

    def calls(self, name, prefix=""):
        path = self.fake / name
        lines = path.read_text().splitlines() if path.exists() else []
        return [line for line in lines if line.startswith(prefix)]

    def current(self):
        return os.readlink(self.sif_dir / "worker-current.sif")


@pytest.fixture
def hpc(tmp_path):
    return Hpc(tmp_path)


def test_waits_for_the_image_before_moving_code(hpc):
    old = hpc.head()
    old_key = hpc.publish()
    assert hpc.run().returncode == 0
    hpc.commit("worker change", {"worker/stub": "changed\n"})
    new_key = hpc.key()
    assert new_key != old_key

    result = hpc.run()

    assert result.returncode == 0
    assert hpc.head() == old
    assert hpc.current() == f"worker-src-{old_key}.sif"
    assert f"waiting: ghcr.io/cadsaltz/gene-autoannotator-worker:src-{new_key}" in hpc.log.read_text()
    assert not list(hpc.sif_dir.glob(".worker-*"))


def test_moves_code_and_sif_together_then_is_a_noop(hpc):
    new = hpc.commit("worker change", {"worker/stub": "changed\n"})
    key = hpc.publish()

    assert hpc.run().returncode == 0
    assert hpc.head() == new
    assert hpc.current() == f"worker-src-{key}.sif"
    assert hpc.sif(key).read_text() == f"image src-{key}\n"
    pulls = hpc.calls("apptainer.log", "pull")
    assert len(pulls) == 1
    assert pulls[0].endswith(f"cache={hpc.sif_dir}/.cache")
    assert hpc.calls("apptainer.log", "cache clean -f --days 14")
    assert len(hpc.calls("pip.log")) == 1
    assert "--requirement=requirements.txt --requirement=requirements-web.txt" in hpc.calls("pip.log")[0]

    assert hpc.run().returncode == 0
    assert len(hpc.calls("apptainer.log", "pull")) == 1
    assert len(hpc.calls("pip.log")) == 1
    assert hpc.log.read_text().splitlines()[-1].endswith(f"up to date at {new[:7]}")


def test_commit_outside_worker_paths_reuses_the_sif(hpc):
    key = hpc.publish()
    hpc.run()
    new = hpc.commit("docs", {"README.md": "x\n"})
    assert hpc.key() == key

    assert hpc.run().returncode == 0

    assert hpc.head() == new
    assert len(hpc.calls("apptainer.log", "pull")) == 1
    assert hpc.current() == f"worker-src-{key}.sif"


def test_reinstalls_only_when_requirements_change(hpc):
    hpc.publish()
    hpc.run()
    hpc.commit("docs only", {"README.md": "x\n"})
    hpc.run()
    assert len(hpc.calls("pip.log")) == 1

    hpc.commit("bump", {"requirements.txt": "httpx==0.28.1\n"})
    hpc.publish()
    assert hpc.run().returncode == 0
    assert len(hpc.calls("pip.log")) == 2


def test_prunes_old_sifs_only_after_the_grace_period(hpc):
    hpc.sif_dir.mkdir()
    for name, age in (("a", 5 * DAY), ("b", 4 * DAY), ("c", 1 * DAY)):
        path = hpc.sif(name * 16)
        path.write_text(name)
        _age(path, age)
    key = hpc.publish()

    assert hpc.run().returncode == 0

    # new (now), c (1 day), b (c replaced it 1 day ago), a (b replaced it 4 days ago)
    assert hpc.sif(key).exists()
    assert hpc.sif("c" * 16).exists()
    assert hpc.sif("b" * 16).exists()
    assert not hpc.sif("a" * 16).exists()


def test_prune_never_deletes_the_current_sif(hpc):
    key = hpc.publish()
    hpc.run()
    _age(hpc.sif(key), 9 * DAY)
    for name in ("b", "c"):
        path = hpc.sif(name * 16)
        path.write_text(name)
        _age(path, 3 * DAY)

    assert hpc.run().returncode == 0

    assert hpc.current() == f"worker-src-{key}.sif"
    assert hpc.sif(key).exists()


def test_code_only_mode_skips_apptainer(hpc):
    new = hpc.commit("worker change", {"worker/stub": "changed\n"})

    assert hpc.run(GAA_PULL_SIF="0").returncode == 0

    assert hpc.head() == new
    assert hpc.calls("apptainer.log") == []
    assert not hpc.sif_dir.exists()


def test_diverged_checkout_is_left_alone(hpc):
    hpc.publish()
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
