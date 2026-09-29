"""deploy/scripts/migrate-to-prod-compose.sh against a fake `docker` CLI.

Volumes are directories under a temp root; `docker run` executes the script's
Python helper locally with the container mount paths rewritten to those
directories. Read-only mounts are chmod'ed read-only for the run.
"""

import hashlib
import json
import os
import sqlite3
import stat
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "deploy" / "scripts" / "migrate-to-prod-compose.sh"

FAKE_DOCKER = r'''#!/usr/bin/env python3
import json, os, subprocess, sys
from pathlib import Path

root = Path(os.environ["FAKE_DOCKER_ROOT"])
volumes = root / "volumes"
volumes.mkdir(exist_ok=True)
args = sys.argv[1:]
with open(root / "calls.log", "a") as log:
    log.write(" ".join(args[:3]) + "\n")


def labels(name):
    path = volumes / f"{name}.labels.json"
    return json.loads(path.read_text()) if path.exists() else {}


def filters(argv):
    out = []
    for i, arg in enumerate(argv):
        if arg == "--filter":
            out.append(argv[i + 1])
    return out


if args[:2] == ["volume", "ls"]:
    for vol in sorted(p for p in volumes.iterdir() if p.is_dir()):
        wanted = [f.removeprefix("label=") for f in filters(args) if f.startswith("label=")]
        have = labels(vol.name)
        if all(have.get(w.split("=", 1)[0]) == w.split("=", 1)[1] if "=" in w else w in have for w in wanted):
            print(vol.name)
    sys.exit(0)
if args[:2] == ["volume", "inspect"]:
    sys.exit(0 if (volumes / args[2]).is_dir() else 1)
if args[:2] == ["volume", "create"]:
    name = args[-1]
    found = {}
    for i, arg in enumerate(args):
        if arg == "--label":
            key, value = args[i + 1].split("=", 1)
            found[key] = value
    (volumes / name).mkdir()
    (volumes / f"{name}.labels.json").write_text(json.dumps(found))
    print(name)
    sys.exit(0)
if args[0] == "ps":
    running = (root / "running").read_text().split() if (root / "running").exists() else []
    for f in filters(args):
        if f.startswith("volume=") and f.removeprefix("volume=") in running:
            print("c0ffee")
    sys.exit(0)
if args[:2] == ["image", "inspect"]:
    sys.exit(0 if not (root / "no-image").exists() else 1)
if args[0] == "run":
    env = dict(os.environ)
    mounts = []
    i = 1
    while i < len(args):
        if args[i] == "-e":
            key, value = args[i + 1].split("=", 1)
            env[key] = value
            i += 2
        elif args[i] == "-v":
            parts = args[i + 1].split(":")
            src, dst = parts[0], parts[1]
            mode = parts[2] if len(parts) > 2 else "rw"
            host = src if src.startswith("/") else str(volumes / src)
            mounts.append((host, dst, mode))
            i += 2
        elif args[i] in ("--user", "--network", "--entrypoint"):
            i += 2
        elif args[i] == "--rm":
            i += 1
        elif args[i] == "-c":
            code = args[i + 1]
            i += 2
        else:
            i += 1
    for host, dst, _mode in mounts:
        code = code.replace(f'"{dst}"', repr(host))
    code = "import os\nos.lchown = lambda *a, **k: None\n" + code
    readonly = [host for host, _dst, mode in mounts if mode == "ro"]
    modes = {}
    for host in readonly:
        for dirpath, dirnames, filenames in os.walk(host):
            for name in [dirpath] + [os.path.join(dirpath, n) for n in filenames]:
                modes[name] = os.stat(name).st_mode
                os.chmod(name, modes[name] & ~0o222)
    try:
        sys.exit(subprocess.run([sys.executable, "-c", code], env=env).returncode)
    finally:
        for name, mode in modes.items():
            os.chmod(name, mode)
print("fake docker: unsupported " + " ".join(args), file=sys.stderr)
sys.exit(2)
'''


@pytest.fixture
def docker(tmp_path):
    root = tmp_path / "docker"
    root.mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "docker"
    fake.write_text(FAKE_DOCKER, encoding="utf-8")
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    return root, bin_dir


def _volume(root, name, project, volume):
    path = root / "volumes" / name
    path.mkdir(parents=True)
    labels = {"com.docker.compose.project": project, "com.docker.compose.volume": volume}
    (root / "volumes" / f"{name}.labels.json").write_text(json.dumps(labels))
    return path


def _old_stack(root, *, leave_wal=True):
    backend = _volume(root, "compose_backend-data", "compose", "backend-data")
    profiles = _volume(root, "compose_profiles-data", "compose", "profiles-data")
    connection = sqlite3.connect(backend / "jobs.sqlite3")
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA wal_autocheckpoint=0")
    connection.execute("CREATE TABLE users (id TEXT PRIMARY KEY, email TEXT)")
    connection.execute("CREATE TABLE annotation_jobs (id TEXT PRIMARY KEY, status TEXT)")
    connection.execute("INSERT INTO users VALUES ('u1', 'a@example.org'), ('u2', 'b@example.org')")
    connection.executemany(
        "INSERT INTO annotation_jobs VALUES (?, 'completed')", [(f"j{i}",) for i in range(5)]
    )
    connection.commit()
    (profiles / "mtb.json").write_text('{"profile_id": "mtb"}')
    (profiles / ".seeded").write_text("")
    if not leave_wal:
        connection.close()
        return backend, profiles, None
    assert (backend / "jobs.sqlite3-wal").stat().st_size > 0
    return backend, profiles, connection


def _run(docker, *args):
    root, bin_dir = docker
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "FAKE_DOCKER_ROOT": str(root)}
    return subprocess.run(
        ["bash", str(SCRIPT), *args], capture_output=True, text=True, env=env, timeout=60
    )


def _digest(path):
    return {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(path.iterdir())
        if p.is_file()
    }


def test_offline_copy_recovers_wal_rows_and_leaves_the_source_untouched(docker):
    root, _bin = docker
    backend, profiles, connection = _old_stack(root)
    before = (_digest(backend), _digest(profiles))

    result = _run(docker)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "users=2, annotation_jobs=5" in result.stdout
    assert "2 profile entries" in result.stdout
    assert (_digest(backend), _digest(profiles)) == before
    connection.close()

    target = root / "volumes" / "gaa_backend-data"
    assert sorted(p.name for p in target.iterdir()) == ["jobs.sqlite3"]
    copy = sqlite3.connect(target / "jobs.sqlite3")
    assert copy.execute("SELECT COUNT(*) FROM users").fetchone() == (2,)
    assert copy.execute("SELECT COUNT(*) FROM annotation_jobs").fetchone() == (5,)
    assert copy.execute("PRAGMA journal_mode").fetchone() == ("delete",)
    copy.close()

    target_profiles = root / "volumes" / "gaa_profiles-data"
    assert sorted(p.name for p in target_profiles.iterdir()) == [".seeded", "mtb.json"]
    labels = json.loads((root / "volumes" / "gaa_backend-data.labels.json").read_text())
    assert labels == {"com.docker.compose.project": "gaa", "com.docker.compose.volume": "backend-data"}


def test_refuses_a_non_empty_target_and_force_moves_it_aside(docker):
    root, _bin = docker
    _old_stack(root, leave_wal=False)
    assert _run(docker).returncode == 0

    again = _run(docker)
    assert again.returncode == 1
    assert "refusing to overwrite" in again.stderr

    target = root / "volumes" / "gaa_backend-data"
    (target / "jobs.sqlite3").write_bytes(b"stale")
    forced = _run(docker, "--force")
    assert forced.returncode == 0, forced.stdout + forced.stderr
    aside = [p for p in target.iterdir() if p.name.startswith(".pre-migrate-")]
    assert len(aside) == 1
    assert (aside[0] / "jobs.sqlite3").read_bytes() == b"stale"
    copy = sqlite3.connect(target / "jobs.sqlite3")
    assert copy.execute("SELECT COUNT(*) FROM users").fetchone() == (2,)
    copy.close()
    profiles_aside = [
        p for p in (root / "volumes" / "gaa_profiles-data").iterdir() if p.name.startswith(".pre-migrate-")
    ]
    assert len(profiles_aside) == 1


def test_offline_refuses_while_the_old_backend_runs_and_online_copies(docker):
    root, _bin = docker
    _old_stack(root, leave_wal=False)
    (root / "running").write_text("compose_backend-data\n")

    refused = _run(docker)
    assert refused.returncode == 1
    assert "Stop the old backend first" in refused.stderr
    assert not (root / "volumes" / "gaa_backend-data").exists()

    online = _run(docker, "--online", "--to-project", "gaa-staging")
    assert online.returncode == 0, online.stdout + online.stderr
    copy = sqlite3.connect(root / "volumes" / "gaa-staging_backend-data" / "jobs.sqlite3")
    assert copy.execute("SELECT COUNT(*) FROM annotation_jobs").fetchone() == (5,)
    copy.close()


def test_refuses_while_the_target_stack_runs(docker):
    root, _bin = docker
    _old_stack(root, leave_wal=False)
    _volume(root, "gaa_backend-data", "gaa", "backend-data")
    (root / "running").write_text("gaa_backend-data\n")
    result = _run(docker)
    assert result.returncode == 1
    assert "running container uses target gaa_backend-data" in result.stderr


def test_missing_source_lists_candidates(docker):
    root, _bin = docker
    _volume(root, "old_backend-data", "old", "backend-data")
    result = _run(docker)
    assert result.returncode == 1
    assert "found 0" in result.stderr
    assert "pass --from-project" in result.stderr


def test_dry_run_changes_nothing(docker):
    root, _bin = docker
    _old_stack(root, leave_wal=False)
    result = _run(docker, "--dry-run")
    assert result.returncode == 0, result.stderr
    assert "dry run: nothing changed" in result.stdout
    assert not (root / "volumes" / "gaa_backend-data").exists()


def test_same_source_and_target_is_rejected(docker):
    root, _bin = docker
    _old_stack(root, leave_wal=False)
    result = _run(docker, "--from-project", "compose", "--to-project", "compose")
    assert result.returncode == 1
    assert "same volume" in result.stderr
