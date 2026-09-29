import shutil
from pathlib import Path

# Relative to the process cwd: /state in the compose deploy, the repo root locally.
DEFAULT_DB_PATH = Path("backend/jobs.sqlite3")
LEGACY_DB_PATH = Path("coordinator/jobs.sqlite3")


def migrate_legacy_db_if_needed(dest: Path = DEFAULT_DB_PATH) -> Path:
    """One-time copy of coordinator SQLite into backend/ if only the old path exists."""
    dest = Path(dest)
    if dest.exists():
        return dest
    legacy = LEGACY_DB_PATH
    if not legacy.exists():
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(legacy, dest)
    for suffix in ("-wal", "-shm"):
        side = Path(str(legacy) + suffix)
        if side.exists():
            shutil.copy2(side, Path(str(dest) + suffix))
    return dest
