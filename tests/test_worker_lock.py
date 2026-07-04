import os

import pytest


def test_second_lock_exits(tmp_path, monkeypatch):
    from worker.lock import WorkerLock, acquire_worker_lock

    monkeypatch.setattr("worker.lock._pid_alive", lambda pid: pid > 0)
    monkeypatch.setattr(
        "worker.lock.sys.exit",
        lambda code: (_ for _ in ()).throw(SystemExit(code)),
    )

    lock_path = tmp_path / "worker.pid"
    lock = acquire_worker_lock(lock_path)
    assert isinstance(lock, WorkerLock)
    assert lock.path == lock_path
    assert lock_path.read_text().strip() == str(os.getpid())

    with pytest.raises(SystemExit) as exc_info:
        acquire_worker_lock(lock_path)
    assert exc_info.value.code == 1
