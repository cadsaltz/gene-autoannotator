"""Control-plane backups to MongoDB GridFS, restore, and job retention.

A snapshot is a gzip tarball with a consistent copy of the control-plane SQLite
database (users, sessions, sign-in codes, jobs, batches, workers, audit log,
rate limits) and the top-level files of the profiles directory. It is exactly
as sensitive as the database itself.
"""

import contextlib
import io
import logging
import math
import os
import shutil
import sqlite3
import tarfile
import tempfile
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath

from .annotation_store import MONGO_DATABASE_NAME, mongo_uri_from_env

log = logging.getLogger(__name__)

BACKUP_BUCKET = "control_plane_backups"
DB_MEMBER = "control-plane.sqlite3"
PROFILES_MEMBER_DIR = "profiles"
DEFAULT_INTERVAL_SECONDS = 21600
MAX_INTERVAL_SECONDS = 7 * 86400
DEFAULT_KEEP = 28
DEFAULT_RETENTION_DAYS = 0
RETENTION_INTERVAL_SECONDS = 86400
FIRST_RUN_DELAY_SECONDS = 60
MONGO_SERVER_SELECTION_TIMEOUT_MS = 10000
# A leftover journal or WAL next to a restored file would be replayed into it.
_SQLITE_SIDECARS = ("-wal", "-shm", "-journal")


class BackupError(RuntimeError):
    """A backup or restore could not be performed."""


class BackupUnavailable(BackupError):
    """Backup storage (MongoDB) is not configured."""


def _env_number(name, default):
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = float(raw.strip())
    except ValueError:
        value = None
    if value is None or not math.isfinite(value):
        log.warning("Ignoring invalid %s=%r; using default %s", name, raw, default)
        return default
    return value


@dataclass(frozen=True)
class BackupConfig:
    interval_seconds: float = DEFAULT_INTERVAL_SECONDS
    keep: int = DEFAULT_KEEP
    retention_days: float = DEFAULT_RETENTION_DAYS
    mongo_configured: bool = False

    @classmethod
    def from_env(cls) -> "BackupConfig":
        keep = int(_env_number("BACKUP_KEEP", DEFAULT_KEEP))
        if keep < 1:
            log.warning("BACKUP_KEEP=%r is below 1; keeping 1 backup", os.getenv("BACKUP_KEEP"))
            keep = 1
        return cls(
            # Event.wait raises OverflowError beyond threading.TIMEOUT_MAX.
            interval_seconds=min(
                _env_number("BACKUP_INTERVAL_SECONDS", DEFAULT_INTERVAL_SECONDS),
                MAX_INTERVAL_SECONDS,
            ),
            keep=keep,
            retention_days=_env_number("JOB_RETENTION_DAYS", DEFAULT_RETENTION_DAYS),
            mongo_configured=bool(mongo_uri_from_env()),
        )

    @property
    def backups_enabled(self) -> bool:
        return self.interval_seconds > 0 and self.mongo_configured

    @property
    def retention_enabled(self) -> bool:
        return self.retention_days > 0


def _now():
    return datetime.now(UTC)


def _profile_files(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    return sorted(
        path for path in directory.iterdir() if not path.is_symlink() and path.is_file()
    )


def _sqlite_files(db_path: Path) -> list[Path]:
    return [db_path, *(Path(f"{db_path}{side}") for side in _SQLITE_SIDECARS)]


def _anonymous_owner(info: tarfile.TarInfo) -> tarfile.TarInfo:
    info.uid = info.gid = 0
    info.uname = info.gname = ""
    return info


def _copy_database(source: Path, dest: Path) -> None:
    src = sqlite3.connect(source, timeout=30.0)
    try:
        dst = sqlite3.connect(dest)
        try:
            src.backup(dst)
            # The copy inherits WAL mode; switch back so it is one self-contained file.
            dst.execute("PRAGMA journal_mode=DELETE")
        finally:
            dst.close()
    finally:
        src.close()


def create_snapshot(db_path, profiles_dir) -> bytes:
    """Return a gzip tarball of a consistent DB copy plus the profile files."""
    db_path = Path(db_path)
    if not db_path.is_file():
        raise BackupError(f"database not found: {db_path}")
    buffer = io.BytesIO()
    with tempfile.TemporaryDirectory(prefix="control-plane-backup-") as tmp:
        copy_path = Path(tmp) / DB_MEMBER
        _copy_database(db_path, copy_path)
        with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
            tar.add(copy_path, arcname=DB_MEMBER, filter=_anonymous_owner)
            for path in _profile_files(Path(profiles_dir)):
                tar.add(
                    path,
                    arcname=f"{PROFILES_MEMBER_DIR}/{path.name}",
                    recursive=False,
                    filter=_anonymous_owner,
                )
    return buffer.getvalue()


def _grid(mongo_db):
    """GridFS bucket for a pymongo Database; any other object is used as-is (tests)."""
    from pymongo.database import Database

    if isinstance(mongo_db, Database):
        import gridfs

        return gridfs.GridFS(mongo_db, collection=BACKUP_BUCKET)
    return mongo_db


def _newest_first(grid) -> list:
    return sorted(
        grid.find(),
        key=lambda item: ((item.metadata or {}).get("created_at") or "", item._id),
        reverse=True,
    )


def _db_member_size(payload: bytes) -> int:
    try:
        with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as tar:
            return tar.getmember(DB_MEMBER).size
    except (tarfile.TarError, KeyError) as exc:
        raise BackupError("snapshot has no control-plane database") from exc


def upload_snapshot(mongo_db, payload: bytes, *, keep: int) -> str:
    """Store `payload` and delete all but the newest `keep` snapshots."""
    db_bytes = _db_member_size(payload)
    grid = _grid(mongo_db)
    created = _now()
    file_id = grid.put(
        payload,
        filename=f"control-plane-{created.strftime('%Y%m%dT%H%M%SZ')}.tar.gz",
        metadata={
            "created_at": created.isoformat(),
            "app_version": os.getenv("APP_VERSION", "dev"),
            "db_bytes": db_bytes,
        },
    )
    for stale in _newest_first(grid)[max(1, keep):]:
        try:
            grid.delete(stale._id)
        except Exception:  # noqa: BLE001 - a failed prune must not fail the new backup.
            log.warning("Failed to delete old control-plane backup %s", stale._id, exc_info=True)
    return str(file_id)


def _summary(item) -> dict:
    metadata = item.metadata or {}
    return {
        "id": str(item._id),
        "created_at": metadata.get("created_at") or item.upload_date.isoformat(),
        "size": item.length,
        "app_version": metadata.get("app_version"),
        "db_bytes": metadata.get("db_bytes"),
    }


def list_snapshots(mongo_db) -> list[dict]:
    return [_summary(item) for item in _newest_first(_grid(mongo_db))]


def _find_snapshot(grid, snapshot_id):
    snapshots = _newest_first(grid)
    if snapshot_id in (None, "latest"):
        if not snapshots:
            raise BackupError("no backups found")
        return snapshots[0]
    for item in snapshots:
        if str(item._id) == snapshot_id:
            return item
    raise BackupError(f"no backup with id {snapshot_id!r}")


def _check_targets(db_path: Path, profiles_dir: Path, force: bool) -> None:
    if force:
        return
    if any(path.exists() for path in _sqlite_files(db_path)):
        raise BackupError(
            f"{db_path} already exists; stop the backend and pass --force to move it "
            "aside and restore"
        )
    if _profile_files(profiles_dir):
        raise BackupError(
            f"{profiles_dir} already contains profile files; pass --force to move them "
            "aside and restore"
        )


def _expected_member_name(name: str) -> bool:
    if name == DB_MEMBER:
        return True
    parts = PurePosixPath(name).parts
    return len(parts) == 2 and parts[0] == PROFILES_MEMBER_DIR and parts[1] not in (".", "..")


def _check_member(member: tarfile.TarInfo, dest: Path) -> None:
    try:
        tarfile.data_filter(member, str(dest))
    except tarfile.FilterError as exc:
        raise BackupError(f"unsafe entry in backup: {member.name!r}") from exc
    if not member.isreg() or not _expected_member_name(member.name):
        raise BackupError(f"unexpected entry in backup: {member.name!r}")


def _extract(payload: bytes, staging: Path) -> list[str]:
    """Validate every member, extract into `staging`, and return profile file names."""
    try:
        with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as tar:
            members = tar.getmembers()
            for member in members:
                _check_member(member, staging)
            if DB_MEMBER not in {member.name for member in members}:
                raise BackupError("backup has no control-plane database")
            tar.extractall(staging, members=members, filter="data")
    except (tarfile.TarError, EOFError, OSError) as exc:
        raise BackupError(f"backup archive is unreadable: {exc}") from exc
    return sorted({PurePosixPath(m.name).name for m in members if m.name != DB_MEMBER})


def _check_database(path: Path) -> None:
    try:
        connection = sqlite3.connect(path)
        try:
            result = connection.execute("PRAGMA quick_check").fetchone()
        finally:
            connection.close()
    except sqlite3.DatabaseError as exc:
        raise BackupError(f"backup database is not usable: {exc}") from exc
    if result is None or result[0] != "ok":
        raise BackupError(f"backup database failed its integrity check: {result}")


def _aside_suffix(db_path: Path, profiles_dir: Path) -> str:
    stamp = _now().strftime("%Y%m%dT%H%M%SZ")
    suffix, attempt = f".pre-restore-{stamp}", 1
    while (profiles_dir / suffix).exists() or any(
        Path(f"{db_path}{suffix}{side}").exists() for side in ("", *_SQLITE_SIDECARS)
    ):
        attempt += 1
        suffix = f".pre-restore-{stamp}-{attempt}"
    return suffix


def _move_database_aside(db_path: Path, suffix: str) -> list[Path]:
    moved = []
    # Sidecars keep the moved main file's name as their prefix so SQLite still
    # pairs the moved WAL with the moved database.
    for side in ("", *_SQLITE_SIDECARS):
        source = Path(f"{db_path}{side}")
        if source.exists():
            target = Path(f"{db_path}{suffix}{side}")
            os.replace(source, target)
            moved.append(target)
    return moved


def _replace_profiles(staged: Path, names: list[str], profiles_dir: Path, suffix: str):
    profiles_dir.mkdir(parents=True, exist_ok=True)
    moved = []
    existing = _profile_files(profiles_dir)
    if existing:
        # Inside the profiles dir (not beside it): in Compose it is a volume
        # mount point, and only files inside the volume survive the container.
        aside = profiles_dir / suffix
        aside.mkdir()
        for path in existing:
            os.replace(path, aside / path.name)
        moved.append(aside)
    for name in names:
        shutil.copy2(staged / name, profiles_dir / name)
    return moved


def restore_snapshot(mongo_db, snapshot_id, *, db_path, profiles_dir, force: bool) -> dict:
    """Restore a snapshot (an id or "latest") into `db_path` and `profiles_dir`.

    Refuses to touch existing state unless `force`; forced restores move the
    old DB files and profile files aside instead of deleting them. The backend
    must be stopped: a running process keeps writing to the moved-aside file.
    """
    db_path, profiles_dir = Path(db_path), Path(profiles_dir)
    grid = _grid(mongo_db)
    chosen = _find_snapshot(grid, snapshot_id)
    _check_targets(db_path, profiles_dir, force)
    payload = grid.get(chosen._id).read()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    # Staged beside the DB so the final rename stays on one filesystem (atomic).
    staging = Path(tempfile.mkdtemp(prefix=".restore-", dir=db_path.parent))
    try:
        profile_names = _extract(payload, staging)
        staged_db = staging / DB_MEMBER
        _check_database(staged_db)
        suffix = _aside_suffix(db_path, profiles_dir)
        moved = _move_database_aside(db_path, suffix)
        os.replace(staged_db, db_path)
        moved += _replace_profiles(
            staging / PROFILES_MEMBER_DIR, profile_names, profiles_dir, suffix
        )
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return {
        **_summary(chosen),
        "profiles": len(profile_names),
        "moved_aside": [str(path) for path in moved],
    }


@contextlib.contextmanager
def mongo_database_from_env():
    uri = mongo_uri_from_env()
    if not uri:
        raise BackupUnavailable("MONGO_URI is not configured")
    from pymongo import MongoClient

    client = MongoClient(uri, serverSelectionTimeoutMS=MONGO_SERVER_SELECTION_TIMEOUT_MS)
    try:
        yield client[MONGO_DATABASE_NAME]
    finally:
        client.close()


def run_backup(*, db_path, profiles_dir, keep: int) -> dict:
    payload = create_snapshot(db_path, profiles_dir)
    with mongo_database_from_env() as mongo_db:
        snapshot_id = upload_snapshot(mongo_db, payload, keep=keep)
    log.info("Uploaded control-plane backup %s (%d bytes)", snapshot_id, len(payload))
    return {"id": snapshot_id, "size": len(payload)}


def run_retention_purge(*, store, audit, days, now=None) -> dict:
    """Delete finished jobs (and emptied batches) older than `days` days."""
    cutoff = ((now or _now()) - timedelta(days=days)).isoformat()
    counts = {
        "jobs": store.purge_finished_before(cutoff),
        "batches": store.purge_empty_batches_before(cutoff),
    }
    if counts["jobs"] or counts["batches"]:
        audit.record(
            action="jobs_purged",
            actor_user_id=None,
            details={**counts, "cutoff": cutoff, "retention_days": days, "source": "system"},
        )
        log.info(
            "Purged %d finished jobs and %d empty batches older than %s",
            counts["jobs"],
            counts["batches"],
            cutoff,
        )
    return counts


class PeriodicTask:
    """Daemon thread that runs `run` after a delay, then every interval, until stopped."""

    def __init__(self, *, name, interval_seconds, first_delay_seconds, run):
        self._name = name
        self._interval = interval_seconds
        self._first_delay = first_delay_seconds
        self._run_once = run
        self._stop = threading.Event()
        self._thread = None

    def _run(self):
        delay = self._first_delay
        while not self._stop.wait(delay):
            try:
                self._run_once()
            except Exception:  # noqa: BLE001 - keep the task alive across failures.
                log.exception("%s failed", self._name)
            delay = self._interval

    def start(self):
        if self.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name=self._name, daemon=True)
        self._thread.start()

    def stop(self, timeout=None):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)

    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()


def backup_task(*, config: BackupConfig, db_path, profiles_dir) -> PeriodicTask:
    return PeriodicTask(
        name="control-plane-backup",
        interval_seconds=config.interval_seconds,
        first_delay_seconds=min(FIRST_RUN_DELAY_SECONDS, config.interval_seconds),
        run=lambda: run_backup(db_path=db_path, profiles_dir=profiles_dir, keep=config.keep),
    )


def retention_task(*, config: BackupConfig, store, audit) -> PeriodicTask:
    return PeriodicTask(
        name="job-retention-purge",
        interval_seconds=RETENTION_INTERVAL_SECONDS,
        first_delay_seconds=FIRST_RUN_DELAY_SECONDS,
        run=lambda: run_retention_purge(store=store, audit=audit, days=config.retention_days),
    )
