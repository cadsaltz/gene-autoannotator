import io
import logging
import sqlite3
import tarfile
import threading
import time
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import gridfs
import pytest
from bson import ObjectId
from fastapi.testclient import TestClient

from backend import backup, manage
from backend.audit_store import AuditStore
from backend.auth_store import AuthStore
from backend.batch_store import BatchStore
from backend.job_store import JobStore
from tests.auth_helpers import make_client


class FakeGridOut:
    def __init__(self, file_id, data, *, filename, metadata):
        self._id = file_id
        self._data = data
        self.filename = filename
        self.metadata = metadata
        self.length = len(data)
        self.upload_date = datetime.now(UTC)

    def read(self):
        return self._data


class FakeGridFS:
    """The subset of the legacy ``gridfs.GridFS`` API that backups use."""

    def __init__(self):
        self.files = {}

    def put(self, data, *, filename=None, metadata=None):
        file_id = ObjectId()
        self.files[file_id] = FakeGridOut(
            file_id, bytes(data), filename=filename, metadata=metadata
        )
        return file_id

    def get(self, file_id):
        if file_id not in self.files:
            raise gridfs.errors.NoFile(f"no file {file_id}")
        return self.files[file_id]

    def find(self, *_args, **_kwargs):
        return list(self.files.values())

    def delete(self, file_id):
        self.files.pop(file_id, None)


@pytest.fixture
def grid():
    return FakeGridFS()


@pytest.fixture
def env_grid(monkeypatch, grid):
    @contextmanager
    def fake_database():
        yield grid

    monkeypatch.setattr(backup, "mongo_database_from_env", fake_database)
    return grid


@pytest.fixture
def source(tmp_path):
    """A populated control-plane DB and profiles dir."""
    db_path = tmp_path / "src" / "jobs.sqlite3"
    profiles_dir = tmp_path / "src" / "profiles"
    profiles_dir.mkdir(parents=True)
    auth = AuthStore(db_path)
    user = auth.create_user(email="a@example.com", username="alice")
    jobs = JobStore(db_path)
    job = jobs.create_job({"locus": "Rv0001"}, submitted_by_user_id=user["id"])
    (profiles_dir / "mtb.json").write_text('{"profile_id": "mtb"}\n', encoding="utf-8")
    (profiles_dir / ".seeded").write_text("1\n", encoding="utf-8")
    return {"db": db_path, "profiles": profiles_dir, "user": user, "job": job}


def _targets(tmp_path):
    return tmp_path / "dst" / "backend" / "jobs.sqlite3", tmp_path / "dst" / "profiles"


def _tar_bytes(members):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for info, data in members:
            if data is not None:
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
            else:
                tar.addfile(info)
    return buffer.getvalue()


def _set_finished(db_path, job_id, status, finished_at):
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "UPDATE annotation_jobs SET status = ?, finished_at = ? WHERE id = ?",
            (status, finished_at, job_id),
        )


# --- snapshot round trip ------------------------------------------------------


def test_snapshot_round_trip_restores_rows_and_profiles(tmp_path, grid, source):
    payload = backup.create_snapshot(source["db"], source["profiles"])
    snapshot_id = backup.upload_snapshot(grid, payload, keep=5)
    db_path, profiles_dir = _targets(tmp_path)

    backup.restore_snapshot(
        grid, snapshot_id, db_path=db_path, profiles_dir=profiles_dir, force=False
    )

    assert AuthStore(db_path).get_user(source["user"]["id"])["email"] == "a@example.com"
    restored_job = JobStore(db_path).get_job(source["job"]["id"])
    assert restored_job["request"] == {"locus": "Rv0001"}
    assert restored_job["submitted_by_user_id"] == source["user"]["id"]
    assert (profiles_dir / "mtb.json").read_text(encoding="utf-8") == '{"profile_id": "mtb"}\n'
    assert (profiles_dir / ".seeded").is_file()


def test_snapshot_includes_rows_still_in_the_wal(tmp_path, grid, source):
    held = sqlite3.connect(source["db"])
    held.execute("PRAGMA wal_autocheckpoint=0")
    held.execute(
        "INSERT INTO annotation_jobs (id, status, request_json, created_at) "
        "VALUES ('wal-job', 'queued', '{}', '2026-01-01T00:00:00+00:00')"
    )
    held.commit()
    try:
        assert source["db"].with_name("jobs.sqlite3-wal").stat().st_size > 0
        payload = backup.create_snapshot(source["db"], source["profiles"])
    finally:
        held.close()
    snapshot_id = backup.upload_snapshot(grid, payload, keep=5)
    db_path, profiles_dir = _targets(tmp_path)

    backup.restore_snapshot(
        grid, snapshot_id, db_path=db_path, profiles_dir=profiles_dir, force=False
    )

    assert JobStore(db_path).get_job("wal-job") is not None


def test_snapshot_members_are_relative_and_regular(source):
    payload = backup.create_snapshot(source["db"], source["profiles"])
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as tar:
        members = tar.getmembers()
    assert sorted(m.name for m in members) == [
        backup.DB_MEMBER,
        "profiles/.seeded",
        "profiles/mtb.json",
    ]
    assert all(m.isreg() for m in members)


def test_snapshot_skips_symlinks_and_subdirectories(tmp_path, source):
    outside = tmp_path / "secret.txt"
    outside.write_text("secret", encoding="utf-8")
    (source["profiles"] / "link.json").symlink_to(outside)
    (source["profiles"] / ".pre-restore-old").mkdir()
    (source["profiles"] / ".pre-restore-old" / "old.json").write_text("{}", encoding="utf-8")

    payload = backup.create_snapshot(source["db"], source["profiles"])

    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as tar:
        names = tar.getnames()
    assert "profiles/link.json" not in names
    assert not any("pre-restore" in name for name in names)


def test_snapshot_refuses_missing_database(tmp_path):
    with pytest.raises(backup.BackupError):
        backup.create_snapshot(tmp_path / "missing.sqlite3", tmp_path / "profiles")
    assert not (tmp_path / "missing.sqlite3").exists()


def test_snapshot_without_profiles_dir_has_only_the_database(tmp_path, source):
    payload = backup.create_snapshot(source["db"], tmp_path / "no-profiles")
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as tar:
        assert tar.getnames() == [backup.DB_MEMBER]


# --- upload / list / retention ----------------------------------------------


def test_upload_metadata_has_no_secrets(grid, source, monkeypatch):
    monkeypatch.setenv("APP_VERSION", "1.2.3")
    monkeypatch.setenv("MONGO_URI", "mongodb://user:hunter2@example.com/db")
    payload = backup.create_snapshot(source["db"], source["profiles"])

    snapshot_id = backup.upload_snapshot(grid, payload, keep=5)

    stored = grid.files[ObjectId(snapshot_id)]
    assert set(stored.metadata) == {"created_at", "app_version", "db_bytes"}
    assert stored.metadata["app_version"] == "1.2.3"
    assert stored.metadata["db_bytes"] == len(_db_member_bytes(source))
    assert "hunter2" not in repr(stored.metadata) + str(stored.filename)
    assert stored.read() == payload


def test_keep_retains_only_newest(grid, source):
    payload = backup.create_snapshot(source["db"], source["profiles"])
    ids = [backup.upload_snapshot(grid, payload, keep=2) for _ in range(4)]

    listed = backup.list_snapshots(grid)

    assert [item["id"] for item in listed] == [ids[3], ids[2]]
    assert len(grid.files) == 2


def test_list_snapshots_newest_first_with_sizes(grid, source):
    payload = backup.create_snapshot(source["db"], source["profiles"])
    first = backup.upload_snapshot(grid, payload, keep=5)
    second = backup.upload_snapshot(grid, payload, keep=5)

    listed = backup.list_snapshots(grid)

    assert [item["id"] for item in listed] == [second, first]
    assert listed[0]["size"] == len(payload)
    assert listed[0]["created_at"] >= listed[1]["created_at"]


def test_upload_rejects_payload_without_database(grid):
    with pytest.raises(backup.BackupError):
        backup.upload_snapshot(grid, _tar_bytes([]), keep=5)
    assert grid.files == {}


# --- restore safety ---------------------------------------------------------


def test_restore_refuses_existing_db_without_force(tmp_path, grid, source):
    snapshot_id = backup.upload_snapshot(
        grid, backup.create_snapshot(source["db"], source["profiles"]), keep=5
    )
    db_path, profiles_dir = _targets(tmp_path)
    db_path.parent.mkdir(parents=True)
    db_path.write_bytes(b"existing")

    with pytest.raises(backup.BackupError, match="--force"):
        backup.restore_snapshot(
            grid, snapshot_id, db_path=db_path, profiles_dir=profiles_dir, force=False
        )

    assert db_path.read_bytes() == b"existing"
    assert not profiles_dir.exists()


def test_restore_refuses_leftover_wal_without_force(tmp_path, grid, source):
    snapshot_id = backup.upload_snapshot(
        grid, backup.create_snapshot(source["db"], source["profiles"]), keep=5
    )
    db_path, profiles_dir = _targets(tmp_path)
    db_path.parent.mkdir(parents=True)
    db_path.with_name("jobs.sqlite3-wal").write_bytes(b"stale wal")

    with pytest.raises(backup.BackupError):
        backup.restore_snapshot(
            grid, snapshot_id, db_path=db_path, profiles_dir=profiles_dir, force=False
        )
    assert not db_path.exists()


def test_restore_refuses_nonempty_profiles_dir_without_force(tmp_path, grid, source):
    snapshot_id = backup.upload_snapshot(
        grid, backup.create_snapshot(source["db"], source["profiles"]), keep=5
    )
    db_path, profiles_dir = _targets(tmp_path)
    profiles_dir.mkdir(parents=True)
    (profiles_dir / "local.json").write_text("{}", encoding="utf-8")

    with pytest.raises(backup.BackupError, match="--force"):
        backup.restore_snapshot(
            grid, snapshot_id, db_path=db_path, profiles_dir=profiles_dir, force=False
        )
    assert not db_path.exists()


def test_force_restore_moves_existing_files_aside(tmp_path, grid, source):
    snapshot_id = backup.upload_snapshot(
        grid, backup.create_snapshot(source["db"], source["profiles"]), keep=5
    )
    db_path, profiles_dir = _targets(tmp_path)
    old_auth = AuthStore(db_path)
    old_auth.create_user(email="old@example.com", username=None)
    held = sqlite3.connect(db_path)
    held.execute("PRAGMA wal_autocheckpoint=0")
    held.execute("UPDATE users SET username = 'in-wal'")
    held.commit()
    profiles_dir.mkdir(parents=True)
    (profiles_dir / "old.json").write_text('{"old": true}', encoding="utf-8")
    (profiles_dir / "mtb.json").write_text('{"stale": true}', encoding="utf-8")

    try:
        result = backup.restore_snapshot(
            grid, snapshot_id, db_path=db_path, profiles_dir=profiles_dir, force=True
        )
    finally:
        held.close()

    assert AuthStore(db_path).get_user_by_email("a@example.com") is not None
    assert AuthStore(db_path).get_user_by_email("old@example.com") is None
    aside_dbs = sorted(
        p for p in db_path.parent.glob("jobs.sqlite3.pre-restore-*")
        if not p.name.endswith(("-wal", "-shm"))
    )
    assert len(aside_dbs) == 1
    with sqlite3.connect(aside_dbs[0]) as connection:
        assert connection.execute(
            "SELECT username FROM users WHERE email = 'old@example.com'"
        ).fetchone() == ("in-wal",)
    assert sorted(p.name for p in profiles_dir.glob("*.json")) == ["mtb.json"]
    assert (profiles_dir / "mtb.json").read_text(encoding="utf-8") == '{"profile_id": "mtb"}\n'
    [aside_profiles] = list(profiles_dir.glob(".pre-restore-*"))
    assert (aside_profiles / "old.json").read_text(encoding="utf-8") == '{"old": true}'
    assert (aside_profiles / "mtb.json").read_text(encoding="utf-8") == '{"stale": true}'
    assert str(aside_dbs[0]) in result["moved_aside"]
    assert not list(db_path.parent.glob(".restore-*"))


def test_restore_latest_picks_newest(tmp_path, grid, source):
    backup.upload_snapshot(grid, backup.create_snapshot(source["db"], source["profiles"]), keep=5)
    JobStore(source["db"]).create_job({"locus": "Rv0002"})
    newest = backup.upload_snapshot(
        grid, backup.create_snapshot(source["db"], source["profiles"]), keep=5
    )
    db_path, profiles_dir = _targets(tmp_path)

    result = backup.restore_snapshot(
        grid, "latest", db_path=db_path, profiles_dir=profiles_dir, force=False
    )

    assert result["id"] == newest
    assert JobStore(db_path).queue_summary()["queued"] == 2


def test_restore_unknown_id_or_empty_bucket_errors(tmp_path, grid):
    db_path, profiles_dir = _targets(tmp_path)
    with pytest.raises(backup.BackupError, match="no backups"):
        backup.restore_snapshot(
            grid, "latest", db_path=db_path, profiles_dir=profiles_dir, force=False
        )
    with pytest.raises(backup.BackupError, match="no backup with id"):
        backup.restore_snapshot(
            grid, str(ObjectId()), db_path=db_path, profiles_dir=profiles_dir, force=False
        )


def _upload_raw(grid, payload):
    return str(
        grid.put(
            payload,
            filename="evil.tar.gz",
            metadata={"created_at": datetime.now(UTC).isoformat(), "app_version": "x", "db_bytes": 1},
        )
    )


def _db_member_bytes(source):
    payload = backup.create_snapshot(source["db"], source["profiles"])
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as tar:
        return tar.extractfile(backup.DB_MEMBER).read()


@pytest.mark.parametrize(
    "bad_member",
    [
        ("../escaped.json", tarfile.REGTYPE, None),
        ("profiles/../../escaped.json", tarfile.REGTYPE, None),
        ("/tmp/absolute-escape.json", tarfile.REGTYPE, None),
        ("profiles/link.json", tarfile.SYMTYPE, "/etc/passwd"),
        ("profiles/rel-link.json", tarfile.SYMTYPE, "mtb.json"),
        ("profiles/hard.json", tarfile.LNKTYPE, backup.DB_MEMBER),
        ("profiles/nested/deep.json", tarfile.REGTYPE, None),
        ("unexpected.txt", tarfile.REGTYPE, None),
    ],
)
def test_restore_rejects_unsafe_tar_members(tmp_path, grid, source, bad_member):
    name, kind, linkname = bad_member
    db_info = tarfile.TarInfo(backup.DB_MEMBER)
    bad = tarfile.TarInfo(name)
    bad.type = kind
    data = None
    if linkname is not None:
        bad.linkname = linkname
    else:
        data = b"{}"
    snapshot_id = _upload_raw(grid, _tar_bytes([(db_info, _db_member_bytes(source)), (bad, data)]))
    db_path, profiles_dir = _targets(tmp_path)

    with pytest.raises(backup.BackupError):
        backup.restore_snapshot(
            grid, snapshot_id, db_path=db_path, profiles_dir=profiles_dir, force=False
        )

    assert not db_path.exists()
    assert not (tmp_path / "escaped.json").exists()
    assert not (tmp_path / "dst" / "escaped.json").exists()
    assert not profiles_dir.exists() or not any(profiles_dir.iterdir())
    assert not db_path.parent.exists() or not list(db_path.parent.glob(".restore-*"))


def test_restore_rejects_corrupt_database(tmp_path, grid):
    info = tarfile.TarInfo(backup.DB_MEMBER)
    snapshot_id = _upload_raw(grid, _tar_bytes([(info, b"not a sqlite database" * 100)]))
    db_path, profiles_dir = _targets(tmp_path)

    with pytest.raises(backup.BackupError):
        backup.restore_snapshot(
            grid, snapshot_id, db_path=db_path, profiles_dir=profiles_dir, force=False
        )
    assert not db_path.exists()


# --- retention purge ----------------------------------------------------------


def test_purge_removes_only_finished_jobs_older_than_cutoff(tmp_path):
    db_path = tmp_path / "jobs.sqlite3"
    store = JobStore(db_path)
    old, new = "2026-01-01T00:00:00+00:00", "2026-03-01T00:00:00+00:00"
    cutoff = "2026-02-01T00:00:00+00:00"
    ids = {}
    for status in ("completed", "failed", "cancelled"):
        ids[f"old-{status}"] = store.create_job({})["id"]
        _set_finished(db_path, ids[f"old-{status}"], status, old)
        ids[f"new-{status}"] = store.create_job({})["id"]
        _set_finished(db_path, ids[f"new-{status}"], status, new)
    for status in ("queued", "running"):
        ids[f"old-{status}"] = store.create_job({})["id"]
        _set_finished(db_path, ids[f"old-{status}"], status, old)
    ids["unfinished-completed"] = store.create_job({})["id"]
    _set_finished(db_path, ids["unfinished-completed"], "completed", None)

    assert store.purge_finished_before(cutoff) == 3

    remaining = {key for key, job_id in ids.items() if store.get_job(job_id) is not None}
    assert remaining == {
        "new-completed",
        "new-failed",
        "new-cancelled",
        "old-queued",
        "old-running",
        "unfinished-completed",
    }


def test_purge_empty_batches_only_when_old_and_jobless(tmp_path):
    db_path = tmp_path / "jobs.sqlite3"
    store = JobStore(db_path)
    batches = BatchStore(db_path)
    empty_old = batches.create_batch()["id"]
    with_job_old = batches.create_batch()["id"]
    store.create_job({}, batch_id=with_job_old)
    empty_new = batches.create_batch()["id"]
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "UPDATE annotation_batches SET created_at = '2026-01-01T00:00:00+00:00' "
            "WHERE id IN (?, ?)",
            (empty_old, with_job_old),
        )

    assert store.purge_empty_batches_before("2026-02-01T00:00:00+00:00") == 1

    assert batches.get_batch(empty_old) is None
    assert batches.get_batch(with_job_old) is not None
    assert batches.get_batch(empty_new) is not None


def test_purge_empty_batches_without_batch_table(tmp_path):
    assert JobStore(tmp_path / "jobs.sqlite3").purge_empty_batches_before("2999-01-01") == 0


def test_retention_purge_records_system_audit_event(tmp_path):
    db_path = tmp_path / "jobs.sqlite3"
    store = JobStore(db_path)
    audit = AuditStore(db_path)
    batches = BatchStore(db_path)
    batch_id = batches.create_batch()["id"]
    job_id = store.create_job({}, batch_id=batch_id)["id"]
    now = datetime(2026, 6, 1, tzinfo=UTC)
    long_ago = (now - timedelta(days=40)).isoformat()
    _set_finished(db_path, job_id, "completed", long_ago)
    with sqlite3.connect(db_path) as connection:
        connection.execute("UPDATE annotation_batches SET created_at = ?", (long_ago,))

    counts = backup.run_retention_purge(store=store, audit=audit, days=30, now=now)

    assert counts == {"jobs": 1, "batches": 1}
    [event] = audit.list(action="jobs_purged")
    assert event["actor_user_id"] is None
    assert event["details"] == {
        "jobs": 1,
        "batches": 1,
        "cutoff": (now - timedelta(days=30)).isoformat(),
        "retention_days": 30,
        "source": "system",
    }


def test_retention_purge_with_nothing_to_purge_records_no_event(tmp_path):
    db_path = tmp_path / "jobs.sqlite3"
    audit = AuditStore(db_path)
    counts = backup.run_retention_purge(store=JobStore(db_path), audit=audit, days=30)
    assert counts == {"jobs": 0, "batches": 0}
    assert audit.list(action="jobs_purged") == []


# --- config -----------------------------------------------------------------

CONFIG_ENV = ("BACKUP_INTERVAL_SECONDS", "BACKUP_KEEP", "JOB_RETENTION_DAYS")


def test_config_defaults(monkeypatch):
    for name in (*CONFIG_ENV, "MONGO_URI", "MONGODB_URI"):
        monkeypatch.delenv(name, raising=False)
    config = backup.BackupConfig.from_env()
    assert config.interval_seconds == 21600
    assert config.keep == 28
    assert config.retention_days == 0
    assert not config.mongo_configured
    assert not config.backups_enabled


def test_config_bad_values_fall_back_to_defaults(monkeypatch, caplog):
    monkeypatch.setenv("BACKUP_INTERVAL_SECONDS", "often")
    monkeypatch.setenv("BACKUP_KEEP", "nan")
    monkeypatch.setenv("JOB_RETENTION_DAYS", "forever")
    with caplog.at_level(logging.WARNING, logger="backend.backup"):
        config = backup.BackupConfig.from_env()
    assert (config.interval_seconds, config.keep, config.retention_days) == (21600, 28, 0)
    for name in CONFIG_ENV:
        assert name in caplog.text


def test_config_clamps_interval_and_keep(monkeypatch):
    monkeypatch.setenv("BACKUP_INTERVAL_SECONDS", "1e12")
    monkeypatch.setenv("BACKUP_KEEP", "0")
    config = backup.BackupConfig.from_env()
    assert config.interval_seconds == 7 * 86400
    assert config.keep == 1


def test_config_enabled_needs_interval_and_mongo(monkeypatch):
    monkeypatch.setenv("MONGODB_URI", "mongodb://localhost:1")
    monkeypatch.delenv("MONGO_URI", raising=False)
    monkeypatch.setenv("BACKUP_INTERVAL_SECONDS", "60")
    assert backup.BackupConfig.from_env().backups_enabled
    monkeypatch.setenv("BACKUP_INTERVAL_SECONDS", "0")
    assert not backup.BackupConfig.from_env().backups_enabled


def test_mongo_database_from_env_requires_uri(monkeypatch):
    monkeypatch.delenv("MONGO_URI", raising=False)
    monkeypatch.delenv("MONGODB_URI", raising=False)
    with pytest.raises(backup.BackupUnavailable):
        with backup.mongo_database_from_env():
            pass


# --- periodic task and app lifespan ------------------------------------------


def test_periodic_task_survives_failures():
    calls = []
    done = threading.Event()

    def flaky():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("mongo down")
        done.set()

    task = backup.PeriodicTask(
        name="test", interval_seconds=0.01, first_delay_seconds=0.01, run=flaky
    )
    task.start()
    try:
        assert done.wait(5)
        assert task.is_alive()
    finally:
        task.stop(timeout=5)
    assert not task.is_alive()


def test_app_skips_backup_loop_when_interval_zero(tmp_path, monkeypatch):
    monkeypatch.setenv("MONGO_URI", "mongodb://localhost:1")
    monkeypatch.setenv("BACKUP_INTERVAL_SECONDS", "0")
    client = make_client(tmp_path)
    with TestClient(client.app):
        assert client.app.state.backup_loop is None


def test_app_skips_backup_loop_without_mongo(tmp_path, monkeypatch, caplog):
    monkeypatch.delenv("MONGO_URI", raising=False)
    monkeypatch.delenv("MONGODB_URI", raising=False)
    monkeypatch.setenv("BACKUP_INTERVAL_SECONDS", "60")
    client = make_client(tmp_path)
    with caplog.at_level(logging.INFO), TestClient(client.app):
        assert client.app.state.backup_loop is None
    assert "MONGO_URI" in caplog.text


def test_app_lifespan_runs_backups_after_delay(tmp_path, monkeypatch, env_grid):
    monkeypatch.setenv("MONGO_URI", "mongodb://localhost:1")
    monkeypatch.setenv("BACKUP_INTERVAL_SECONDS", "3600")
    monkeypatch.setattr(backup, "FIRST_RUN_DELAY_SECONDS", 0.01)
    client = make_client(tmp_path)
    with TestClient(client.app):
        loop = client.app.state.backup_loop
        assert loop is not None and loop.is_alive()
        deadline = time.monotonic() + 5
        while not env_grid.files and time.monotonic() < deadline:
            time.sleep(0.01)
        assert len(env_grid.files) == 1
    assert not loop.is_alive()


def test_app_retention_loop_disabled_by_default(tmp_path):
    client = make_client(tmp_path)
    with TestClient(client.app):
        assert client.app.state.retention_loop is None


def test_app_retention_loop_purges_when_enabled(tmp_path, monkeypatch):
    monkeypatch.setenv("JOB_RETENTION_DAYS", "30")
    monkeypatch.setattr(backup, "FIRST_RUN_DELAY_SECONDS", 0.01)
    db_path = tmp_path / "jobs.sqlite3"
    store = JobStore(db_path)
    job_id = store.create_job({})["id"]
    _set_finished(db_path, job_id, "completed", "2000-01-01T00:00:00+00:00")
    client = make_client(tmp_path, job_store=store)
    with TestClient(client.app):
        loop = client.app.state.retention_loop
        assert loop is not None and loop.is_alive()
        deadline = time.monotonic() + 5
        while store.get_job(job_id) is not None and time.monotonic() < deadline:
            time.sleep(0.01)
        assert store.get_job(job_id) is None
    assert not loop.is_alive()


# --- CLI --------------------------------------------------------------------


def test_cli_backup_prints_id_and_size(env_grid, source, capsys):
    code = manage.main(
        ["--db", str(source["db"]), "--profiles-dir", str(source["profiles"]), "backup"]
    )

    assert code == 0
    [stored] = env_grid.files.values()
    out = capsys.readouterr().out
    assert str(stored._id) in out
    assert str(stored.length) in out
    [event] = AuditStore(source["db"]).list(action="backup_created")
    assert event["target_id"] == str(stored._id)
    assert event["details"]["source"] == "cli"


def test_cli_backup_without_mongo_uri_fails(source, monkeypatch, capsys):
    monkeypatch.delenv("MONGO_URI", raising=False)
    monkeypatch.delenv("MONGODB_URI", raising=False)
    code = manage.main(["--db", str(source["db"]), "backup"])
    assert code == 1
    assert "MONGO_URI" in capsys.readouterr().err


def test_cli_backup_refuses_missing_database(tmp_path, env_grid, capsys):
    code = manage.main(["--db", str(tmp_path / "missing.sqlite3"), "backup"])
    assert code == 1
    assert "database not found" in capsys.readouterr().err
    assert env_grid.files == {}


def test_cli_list_backups_prints_table(env_grid, source, capsys):
    payload = backup.create_snapshot(source["db"], source["profiles"])
    first = backup.upload_snapshot(env_grid, payload, keep=5)
    second = backup.upload_snapshot(env_grid, payload, keep=5)
    capsys.readouterr()

    assert manage.main(["--db", str(source["db"]), "list-backups"]) == 0

    lines = capsys.readouterr().out.splitlines()
    assert lines[0].split() == ["ID", "CREATED_AT", "SIZE"]
    assert lines[1].split()[0] == second
    assert lines[2].split()[0] == first
    assert lines[1].split()[2] == str(len(payload))


def test_cli_list_backups_empty(env_grid, tmp_path, capsys):
    assert manage.main(["--db", str(tmp_path / "none.sqlite3"), "list-backups"]) == 0
    assert "No backups." in capsys.readouterr().out


def test_cli_restore_into_missing_db_warns_and_audits(tmp_path, env_grid, source, capsys):
    snapshot_id = backup.upload_snapshot(
        env_grid, backup.create_snapshot(source["db"], source["profiles"]), keep=5
    )
    db_path, profiles_dir = _targets(tmp_path)

    code = manage.main(
        ["--db", str(db_path), "--profiles-dir", str(profiles_dir), "restore"]
    )

    assert code == 0
    captured = capsys.readouterr()
    assert "stop" in captured.err.lower() and "backend" in captured.err.lower()
    assert snapshot_id in captured.out
    assert AuthStore(db_path).get_user_by_email("a@example.com") is not None
    [event] = AuditStore(db_path).list(action="backup_restored")
    assert event["target_id"] == snapshot_id
    assert event["details"]["source"] == "cli"


def test_cli_restore_refuses_existing_db_without_force(tmp_path, env_grid, source, capsys):
    snapshot_id = backup.upload_snapshot(
        env_grid, backup.create_snapshot(source["db"], source["profiles"]), keep=5
    )
    db_path, profiles_dir = _targets(tmp_path)
    AuthStore(db_path).create_user(email="old@example.com", username=None)

    code = manage.main(
        ["--db", str(db_path), "--profiles-dir", str(profiles_dir), "restore", "--id", snapshot_id]
    )

    assert code == 1
    assert "--force" in capsys.readouterr().err
    assert AuthStore(db_path).get_user_by_email("old@example.com") is not None

    code = manage.main(
        [
            "--db", str(db_path), "--profiles-dir", str(profiles_dir),
            "restore", "--id", snapshot_id, "--force",
        ]
    )
    assert code == 0
    assert AuthStore(db_path).get_user_by_email("old@example.com") is None
    assert "pre-restore" in capsys.readouterr().out
