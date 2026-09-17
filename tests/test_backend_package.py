from pathlib import Path


def test_backend_is_canonical_package():
    from backend.api import DEFAULT_DB_PATH, app, create_app

    assert app is not None
    assert callable(create_app)
    assert DEFAULT_DB_PATH == Path("backend/jobs.sqlite3")


def test_migrate_legacy_db_copies_when_dest_missing(tmp_path, monkeypatch):
    from backend import api as backend_api

    legacy = tmp_path / "coordinator" / "jobs.sqlite3"
    dest = tmp_path / "backend" / "jobs.sqlite3"
    legacy.parent.mkdir(parents=True)
    legacy.write_bytes(b"legacy-db")
    (tmp_path / "coordinator" / "jobs.sqlite3-wal").write_bytes(b"wal")
    (tmp_path / "coordinator" / "jobs.sqlite3-shm").write_bytes(b"shm")

    monkeypatch.setattr(backend_api, "LEGACY_DB_PATH", legacy)
    monkeypatch.setattr(backend_api, "DEFAULT_DB_PATH", dest)

    result = backend_api._migrate_legacy_db_if_needed(dest)

    assert result == dest
    assert dest.read_bytes() == b"legacy-db"
    assert Path(str(dest) + "-wal").read_bytes() == b"wal"
    assert Path(str(dest) + "-shm").read_bytes() == b"shm"


def test_migrate_legacy_db_skips_when_dest_exists(tmp_path, monkeypatch):
    from backend import api as backend_api

    legacy = tmp_path / "coordinator" / "jobs.sqlite3"
    dest = tmp_path / "backend" / "jobs.sqlite3"
    legacy.parent.mkdir(parents=True)
    dest.parent.mkdir(parents=True)
    legacy.write_bytes(b"legacy-db")
    dest.write_bytes(b"new-db")

    monkeypatch.setattr(backend_api, "LEGACY_DB_PATH", legacy)
    monkeypatch.setattr(backend_api, "DEFAULT_DB_PATH", dest)

    result = backend_api._migrate_legacy_db_if_needed(dest)

    assert result == dest
    assert dest.read_bytes() == b"new-db"
