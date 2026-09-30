import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .quotas import QuotaExceeded, env_int

HOUR_SECONDS = 3600
DAY_SECONDS = 86400
PRUNE_AFTER = timedelta(days=2)

RATE_LIMIT_DEFAULTS = {
    "IP_SIGNUPS_PER_DAY": 5,
    "IP_LOGINS_PER_HOUR": 30,
    "IP_SUBMITS_PER_HOUR": 30,
    "OTP_SENDS_PER_EMAIL_PER_HOUR": 5,
}


def rate_limit_from_env(name: str) -> int:
    return env_int(name, RATE_LIMIT_DEFAULTS[name])


class RateLimited(QuotaExceeded):
    def __init__(self, message: str):
        super().__init__("rate_limited", message)


class RateLimiter:
    def __init__(self, db_path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self):
        connection = sqlite3.connect(self.db_path, timeout=30.0, isolation_level=None)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    def _initialize(self):
        with self._connect() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS rate_events (bucket TEXT, key TEXT, created_at TEXT)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_rate_events_bucket_key_created "
                "ON rate_events (bucket, key, created_at)"
            )

    def _delete(self, where: str, params) -> int:
        connection = self._connect()
        try:
            return connection.execute(f"DELETE FROM rate_events WHERE {where}", params).rowcount
        finally:
            connection.close()

    def forget_key(self, key: str) -> int:
        return self._delete("key = ?", (key,))

    def purge_before(self, cutoff: str) -> int:
        return self._delete("created_at < ?", (cutoff,))

    @staticmethod
    def _count(connection, bucket, key, window_start) -> int:
        (count,) = connection.execute(
            "SELECT COUNT(*) FROM rate_events WHERE bucket = ? AND key = ? AND created_at > ?",
            (bucket, key, window_start),
        ).fetchone()
        return count

    def would_allow(self, bucket: str, key: str, window_seconds: int, limit: int) -> bool:
        window_start = (datetime.now(UTC) - timedelta(seconds=window_seconds)).isoformat()
        connection = self._connect()
        try:
            return self._count(connection, bucket, key, window_start) < limit
        finally:
            connection.close()

    def hit(self, bucket: str, key: str, window_seconds: int, limit: int) -> bool:
        now = datetime.now(UTC)
        window_start = (now - timedelta(seconds=window_seconds)).isoformat()
        # BEGIN IMMEDIATE takes the write lock before counting so concurrent
        # hits cannot all see the same count and overshoot the limit.
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "DELETE FROM rate_events WHERE bucket = ? AND created_at < ?",
                (bucket, (now - PRUNE_AFTER).isoformat()),
            )
            allowed = self._count(connection, bucket, key, window_start) < limit
            if allowed:
                connection.execute(
                    "INSERT INTO rate_events (bucket, key, created_at) VALUES (?, ?, ?)",
                    (bucket, key, now.isoformat()),
                )
            connection.execute("COMMIT")
            return allowed
        except BaseException:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()
