"""deploy/scripts/worker-image-key.sh must cover exactly what Dockerfile.worker copies."""

import os
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
KEY_SCRIPT = REPO_ROOT / "deploy" / "scripts" / "worker-image-key.sh"
DOCKERFILE = REPO_ROOT / "deploy" / "docker" / "Dockerfile.worker"

GIT_ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.org",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.org",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
}


def _key_paths():
    out = subprocess.run([str(KEY_SCRIPT), "--paths"], check=True, capture_output=True, text=True).stdout
    return out.split()


def _copy_sources():
    text = DOCKERFILE.read_text().replace("\\\n", " ")
    sources = set()
    for line in text.splitlines():
        words = shlex.split(line, comments=True)
        if not words or words[0].upper() not in ("COPY", "ADD"):
            continue
        args = [w for w in words[1:] if not w.startswith("--")]
        assert not any(w.startswith("--from") for w in words), "COPY --from is not a build-context path"
        sources.update(src.rstrip("/") for src in args[:-1])
    return sources


def test_key_paths_match_dockerfile_copy_sources():
    extra = {"deploy/docker/Dockerfile.worker", ".dockerignore"}
    assert set(_key_paths()) == _copy_sources() | extra
    assert _copy_sources(), "no COPY lines parsed"


def test_key_paths_exist_in_the_repo():
    for rel in _key_paths():
        assert (REPO_ROOT / rel).exists(), rel


def _git(cwd, *args):
    return subprocess.run(
        ["git", *args], cwd=cwd, env={**os.environ, **GIT_ENV}, check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    _git(tmp_path, "init", "-q", "-b", "master")
    for rel in _key_paths():
        target = tmp_path / rel
        if "." in target.name:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(rel)
        else:
            target.mkdir(parents=True, exist_ok=True)
            (target / "stub").write_text(rel)
    (tmp_path / "README.md").write_text("x")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "initial")
    return tmp_path


def _key(repo, *args):
    return subprocess.run([str(KEY_SCRIPT), *args], cwd=repo, capture_output=True, text=True)


def _commit(repo, rel, text):
    (repo / rel).write_text(text)
    _git(repo, "commit", "-q", "-am", rel)


def test_key_changes_only_with_worker_paths(repo):
    first = _key(repo).stdout.strip()
    assert len(first) == 16

    _commit(repo, "README.md", "changed")
    assert _key(repo).stdout.strip() == first
    assert _key(repo, "HEAD~1").stdout.strip() == first

    _commit(repo, "worker/stub", "changed")
    assert _key(repo).stdout.strip() != first

    _commit(repo, "deploy/docker/Dockerfile.worker", "changed")
    assert len({first, _key(repo, "HEAD~1").stdout.strip(), _key(repo).stdout.strip()}) == 3


def test_key_fails_for_a_missing_path_or_bad_commit(repo):
    shutil.rmtree(repo / "goresolve")
    _git(repo, "commit", "-q", "-am", "drop goresolve")
    result = _key(repo)
    assert result.returncode == 1
    assert result.stdout == ""
    assert "goresolve missing" in result.stderr

    assert _key(repo, "no-such-ref").returncode == 1
