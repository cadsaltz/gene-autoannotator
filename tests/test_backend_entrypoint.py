import importlib.util
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT = REPO_ROOT / "deploy" / "docker" / "backend-entrypoint.py"


def _load_entrypoint():
    spec = importlib.util.spec_from_file_location("backend_entrypoint", ENTRYPOINT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(tmp_path, data_dirs, *command):
    env = {**os.environ, "APP_DATA_DIRS": ":".join(str(path) for path in data_dirs)}
    return subprocess.run(
        [sys.executable, str(ENTRYPOINT), *command],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


@pytest.mark.skipif(os.getuid() == 0, reason="exercises the non-root path")
def test_non_root_start_execs_command_when_data_dirs_writable(tmp_path):
    data = tmp_path / "state"
    data.mkdir()
    result = _run(tmp_path, [data], sys.executable, "-c", "print('started')")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "started"


@pytest.mark.skipif(os.getuid() == 0, reason="root can write any dir")
def test_non_root_start_fails_clearly_on_unwritable_data_dir(tmp_path):
    data = tmp_path / "state"
    data.mkdir()
    data.chmod(stat.S_IRUSR | stat.S_IXUSR)
    try:
        result = _run(tmp_path, [data], sys.executable, "-c", "print('started')")
    finally:
        data.chmod(stat.S_IRWXU)
    assert result.returncode == 1
    assert "started" not in result.stdout
    assert f"cannot write {data}" in result.stderr
    assert "chown -R" in result.stderr


def test_missing_command_is_a_usage_error(tmp_path):
    result = _run(tmp_path, [])
    assert result.returncode == 2
    assert "usage:" in result.stderr


def test_chown_tree_only_touches_mismatched_paths(tmp_path, monkeypatch):
    entrypoint = _load_entrypoint()
    # /proc/self/fd links resolve symlinks, so compare against the real path.
    tmp_path = tmp_path.resolve()
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "jobs.sqlite3").write_text("", encoding="utf-8")
    (tmp_path / "link").symlink_to("/etc/passwd")
    (tmp_path / "dirlink").symlink_to("/etc")
    calls = []

    def fake_chown(name, uid, gid, *, dir_fd=None, follow_symlinks=True):
        assert follow_symlinks is False
        parent = os.readlink(f"/proc/self/fd/{dir_fd}") if dir_fd is not None else ""
        calls.append(os.path.join(parent, name))

    monkeypatch.setattr(entrypoint.os, "chown", fake_chown)

    assert entrypoint._chown_tree(str(tmp_path), os.getuid(), os.getgid()) == 0
    assert calls == []

    changed = entrypoint._chown_tree(str(tmp_path), os.getuid() + 1, os.getgid())
    expected = [tmp_path, tmp_path / "sub", tmp_path / "sub" / "jobs.sqlite3", tmp_path / "link", tmp_path / "dirlink"]
    assert changed == len(expected)
    assert sorted(calls) == sorted(str(path) for path in expected)
