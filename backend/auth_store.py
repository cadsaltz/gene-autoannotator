import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path

from .access import BOOTSTRAP_ADMIN_EMAIL, ROLES, STATUSES, initial_role_for


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
            role_added = self._ensure_user_column(
                connection, "role", "TEXT NOT NULL DEFAULT 'user'"
            )
            self._ensure_user_column(connection, "status", "TEXT NOT NULL DEFAULT 'active'")
            self._ensure_user_column(connection, "quota_max_active", "INTEGER")
            self._ensure_user_column(connection, "quota_max_per_day", "INTEGER")
            self._ensure_user_column(connection, "quota_max_batch", "INTEGER")
            self._ensure_user_column(connection, "terms_version", "TEXT")
            self._ensure_user_column(connection, "terms_accepted_at", "TEXT")
            self._ensure_user_column(connection, "last_login_at", "TEXT")
            # Promote only when the role column is first added, so a later
            # demotion of the bootstrap admin is not undone on restart.
            if role_added:
                connection.execute(
                    "UPDATE users SET role = 'admin' WHERE email = ?",
                    (BOOTSTRAP_ADMIN_EMAIL,),
                )

    def _ensure_user_column(self, connection, column_name, column_type) -> bool:
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(users)").fetchall()
        }
        if column_name in columns:
            return False
        connection.execute(f"ALTER TABLE users ADD COLUMN {column_name} {column_type}")
        return True

    def create_user(
        self, *, email: str, username: str | None, status: str = "active"
    ) -> dict:
        if status not in STATUSES:
            raise ValueError(f"invalid status: {status}")
        user_id = str(uuid.uuid4())
        normalized = _normalize_email(email)
        created_at = _now_iso()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO users (
                    id, email, username, email_verified, created_at, role, status
                ) VALUES (?, ?, ?, 0, ?, ?, ?)
                """,
                (
                    user_id,
                    normalized,
                    username,
                    created_at,
                    initial_role_for(normalized),
                    status,
                ),
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
        return self._require_user(user_id)

    def set_role(self, user_id: str, role: str) -> dict:
        if role not in ROLES:
            raise ValueError(f"invalid role: {role}")
        with self._connect() as connection:
            connection.execute(
                "UPDATE users SET role = ? WHERE id = ?",
                (role, user_id),
            )
        return self._require_user(user_id)

    def set_status(self, user_id: str, status: str) -> dict:
        if status not in STATUSES:
            raise ValueError(f"invalid status: {status}")
        with self._connect() as connection:
            connection.execute(
                "UPDATE users SET status = ? WHERE id = ?",
                (status, user_id),
            )
        return self._require_user(user_id)

    def set_quota_overrides(
        self,
        user_id: str,
        *,
        max_active: int | None,
        max_per_day: int | None,
        max_batch: int | None,
    ) -> dict:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE users
                SET quota_max_active = ?, quota_max_per_day = ?, quota_max_batch = ?
                WHERE id = ?
                """,
                (max_active, max_per_day, max_batch, user_id),
            )
        return self._require_user(user_id)

    def record_terms_acceptance(self, user_id: str, version: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE users SET terms_version = ?, terms_accepted_at = ? WHERE id = ?",
                (version, _now_iso(), user_id),
            )

    def mark_login(self, user_id: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE users SET last_login_at = ? WHERE id = ?",
                (_now_iso(), user_id),
            )

    def list_users(self, *, query: str | None = None, limit: int = 200) -> list[dict]:
        sql = "SELECT * FROM users"
        params: list = []
        if query:
            sql += " WHERE email LIKE ? OR username LIKE ?"
            pattern = f"%{query.strip()}%"
            params.extend([pattern, pattern])
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self._connect() as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(sql, params).fetchall()
        return [self._row_to_user(row) for row in rows]

    def count_admins(self) -> int:
        with self._connect() as connection:
            return connection.execute(
                "SELECT COUNT(*) FROM users WHERE role = 'admin' AND status = 'active'"
            ).fetchone()[0]

    def revoke_sessions(self, user_id: str) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM sessions WHERE user_id = ?",
                (user_id,),
            )
        return cursor.rowcount

    def delete_user(self, user_id: str) -> bool:
        user = self.get_user(user_id)
        if user is None:
            return False
        with self._connect() as connection:
            connection.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
            connection.execute(
                "DELETE FROM login_codes WHERE email = ?",
                (user["email"],),
            )
            connection.execute("DELETE FROM users WHERE id = ?", (user_id,))
        return True

    def _require_user(self, user_id: str) -> dict:
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
            "role": row["role"],
            "status": row["status"],
            "quota_max_active": row["quota_max_active"],
            "quota_max_per_day": row["quota_max_per_day"],
            "quota_max_batch": row["quota_max_batch"],
            "terms_version": row["terms_version"],
            "terms_accepted_at": row["terms_accepted_at"],
            "last_login_at": row["last_login_at"],
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
