from __future__ import annotations

import atexit
import os
import sys
from pathlib import Path

_lock_path: Path | None = None


class WorkerLock:
    def __init__(self, path: Path) -> None:
        self.path = path


def _default_lock_path() -> Path:
    if env := os.getenv("WORKER_LOCK_FILE"):
        return Path(env)
    run_dir = Path("/run")
    if run_dir.is_dir() and os.access(run_dir, os.W_OK):
        return run_dir / "gene-autoannotator-worker.pid"
    return Path.home() / ".gene-autoannotator-worker.pid"


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _release_lock() -> None:
    global _lock_path
    if _lock_path is None:
        return
    try:
        _lock_path.unlink(missing_ok=True)
    except OSError:
        pass
    _lock_path = None


def acquire_worker_lock(path: Path | str | None = None) -> WorkerLock:
    global _lock_path
    lock_path = Path(path) if path is not None else _default_lock_path()
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    if lock_path.exists():
        try:
            existing_pid = int(lock_path.read_text().strip())
        except (OSError, ValueError):
            existing_pid = -1
        if _pid_alive(existing_pid):
            print(
                f"Another worker is already running (PID {existing_pid}, lock: {lock_path})",
                file=sys.stderr,
            )
            sys.exit(1)

    lock_path.write_text(str(os.getpid()))
    _lock_path = lock_path
    atexit.register(_release_lock)
    return WorkerLock(lock_path)
