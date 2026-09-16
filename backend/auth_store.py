import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path


def _now_iso():
    return datetime.now(UTC).isoformat()


def _normalize_email(email: str) -> str:
    return email.strip().lower()


class AuthStore:
    def __init__(self, db_path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self):
        connection = sqlite3.connect(self.db_path, timeout=30.0)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    def _initialize(self):
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    username TEXT,
                    email_verified INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS login_codes (
                    id TEXT PRIMARY KEY,
                    email TEXT NOT NULL COLLATE NOCASE,
                    purpose TEXT NOT NULL,
                    code_hash TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    used_at TEXT,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    token_hash TEXT NOT NULL UNIQUE,
                    expires_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    ip TEXT,
                    FOREIGN KEY(user_id) REFERENCES users(id)
                )
                """
            )

    def create_user(self, *, email: str, username: str | None) -> dict:
        user_id = str(uuid.uuid4())
        normalized = _normalize_email(email)
        created_at = _now_iso()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO users (id, email, username, email_verified, created_at)
                VALUES (?, ?, ?, 0, ?)
                """,
                (user_id, normalized, username, created_at),
            )
        return self.get_user(user_id)

    def get_user_by_email(self, email: str) -> dict | None:
        normalized = _normalize_email(email)
        with self._connect() as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                "SELECT * FROM users WHERE email = ?",
                (normalized,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_user(row)

    def get_user(self, user_id: str) -> dict | None:
        with self._connect() as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                "SELECT * FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_user(row)

    def mark_email_verified(self, user_id: str) -> dict:
        with self._connect() as connection:
            connection.execute(
                "UPDATE users SET email_verified = 1 WHERE id = ?",
                (user_id,),
            )
        user = self.get_user(user_id)
        if user is None:
            raise ValueError(f"user not found: {user_id}")
        return user

    def create_login_code(
        self,
        *,
        email: str,
        purpose: str,
        code_hash: str,
        expires_at: str,
    ) -> str:
        normalized = _normalize_email(email)
        code_id = str(uuid.uuid4())
        created_at = _now_iso()
        now = _now_iso()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE login_codes
                SET used_at = ?
                WHERE email = ? AND used_at IS NULL
                """,
                (now, normalized),
            )
            connection.execute(
                """
                INSERT INTO login_codes (
                    id, email, purpose, code_hash, expires_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (code_id, normalized, purpose, code_hash, expires_at, created_at),
            )
        return code_id

    def consume_login_code(self, *, email: str, code_hash: str) -> dict | None:
        normalized = _normalize_email(email)
        now = _now_iso()
        with self._connect() as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                """
                SELECT * FROM login_codes
                WHERE email = ? AND code_hash = ? AND used_at IS NULL
                  AND expires_at > ? AND attempt_count < 5
                """,
                (normalized, code_hash, now),
            ).fetchone()
            if row is None:
                return None
            connection.execute(
                "UPDATE login_codes SET used_at = ? WHERE id = ?",
                (now, row["id"]),
            )
        return self._row_to_login_code(row, used_at=now)

    def register_failed_code_attempt(self, *, email: str, code_hash: str) -> int:
        normalized = _normalize_email(email)
        now = _now_iso()
        with self._connect() as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                """
                SELECT id, attempt_count FROM login_codes
                WHERE email = ? AND used_at IS NULL AND expires_at > ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (normalized, now),
            ).fetchone()
            if row is None:
                return 0
            new_count = row["attempt_count"] + 1
            connection.execute(
                "UPDATE login_codes SET attempt_count = ? WHERE id = ?",
                (new_count, row["id"]),
            )
        return new_count

    def create_session(
        self,
        *,
        user_id: str,
        token_hash: str,
        expires_at: str,
        ip: str | None,
    ) -> str:
        session_id = str(uuid.uuid4())
        now = _now_iso()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO sessions (
                    id, user_id, token_hash, expires_at, created_at, last_seen_at, ip
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (session_id, user_id, token_hash, expires_at, now, now, ip),
            )
        return session_id

    def get_session_user(self, token_hash: str) -> dict | None:
        now = _now_iso()
        with self._connect() as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                """
                SELECT u.* FROM sessions s
                JOIN users u ON u.id = s.user_id
                WHERE s.token_hash = ? AND s.expires_at > ?
                """,
                (token_hash, now),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_user(row)

    def touch_session(self, token_hash: str, expires_at: str) -> None:
        now = _now_iso()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE sessions
                SET last_seen_at = ?, expires_at = ?
                WHERE token_hash = ?
                """,
                (now, expires_at, token_hash),
            )

    def delete_session(self, token_hash: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM sessions WHERE token_hash = ?",
                (token_hash,),
            )

    def _row_to_user(self, row) -> dict:
        return {
            "id": row["id"],
            "email": row["email"],
            "username": row["username"],
            "email_verified": bool(row["email_verified"]),
            "created_at": row["created_at"],
        }

    def _row_to_login_code(self, row, *, used_at: str | None = None) -> dict:
        return {
            "id": row["id"],
            "email": row["email"],
            "purpose": row["purpose"],
            "code_hash": row["code_hash"],
            "expires_at": row["expires_at"],
            "used_at": used_at if used_at is not None else row["used_at"],
            "attempt_count": row["attempt_count"],
            "created_at": row["created_at"],
        }
