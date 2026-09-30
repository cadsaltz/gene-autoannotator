import json
import logging
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path

log = logging.getLogger(__name__)

DEFAULT_LIST_LIMIT = 200
MAX_LIST_LIMIT = 1000


def mask_email(email: str) -> str:
    """Keep the first character and the domain, e.g. ``s***@gmail.com``."""
    local, at, domain = (email or "").strip().lower().partition("@")
    if not at or not local or not domain:
        return "***"
    return f"{local[0]}***@{domain}"


class AuditStore:
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
                CREATE TABLE IF NOT EXISTS audit_events (
                    id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    action TEXT NOT NULL,
                    actor_user_id TEXT,
                    target_type TEXT,
                    target_id TEXT,
                    ip TEXT,
                    details_json TEXT
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_audit_events_created_at "
                "ON audit_events (created_at)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_audit_events_action ON audit_events (action)"
            )
            self._mask_deleted_user_emails(connection)

    @staticmethod
    def _mask_deleted_user_emails(connection):
        rows = connection.execute(
            "SELECT id, details_json FROM audit_events "
            "WHERE action = 'user_delete' AND details_json LIKE '%\"email\"%'"
        ).fetchall()
        for event_id, details_json in rows:
            try:
                details = json.loads(details_json)
            except (TypeError, ValueError):
                continue
            email = details.get("email") if isinstance(details, dict) else None
            if not isinstance(email, str) or "***" in email:
                continue
            details["email"] = mask_email(email)
            connection.execute(
                "UPDATE audit_events SET details_json = ? WHERE id = ?",
                (json.dumps(details), event_id),
            )

    def purge_before(self, cutoff: str) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM audit_events WHERE created_at < ?", (cutoff,)
            )
        return cursor.rowcount

    def record(
        self,
        *,
        action: str,
        actor_user_id: str | None,
        target_type: str | None = None,
        target_id: str | None = None,
        ip: str | None = None,
        details: dict | None = None,
    ) -> None:
        try:
            connection = self._connect()
            try:
                with connection:
                    connection.execute(
                        """
                        INSERT INTO audit_events (
                            id, created_at, action, actor_user_id,
                            target_type, target_id, ip, details_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            str(uuid.uuid4()),
                            datetime.now(UTC).isoformat(),
                            action,
                            actor_user_id,
                            target_type,
                            target_id,
                            ip,
                            json.dumps(details or {}),
                        ),
                    )
            finally:
                connection.close()
        except Exception:  # noqa: BLE001 - auditing must never fail the audited action.
            log.warning("Failed to record audit event %s", action, exc_info=True)

    def list(
        self,
        *,
        limit: int = DEFAULT_LIST_LIMIT,
        action: str | None = None,
        actor_user_id: str | None = None,
        target_id: str | None = None,
        user_id: str | None = None,
    ) -> list[dict]:
        clauses = []
        params = []
        if action is not None:
            clauses.append("e.action = ?")
            params.append(action)
        if actor_user_id is not None:
            clauses.append("e.actor_user_id = ?")
            params.append(actor_user_id)
        if target_id is not None:
            clauses.append("e.target_id = ?")
            params.append(target_id)
        if user_id is not None:
            clauses.append(
                "(e.actor_user_id = ? OR (e.target_type = 'user' AND e.target_id = ?))"
            )
            params.extend([user_id, user_id])
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        limit = max(1, min(int(limit), MAX_LIST_LIMIT))
        connection = self._connect()
        try:
            connection.row_factory = sqlite3.Row
            has_users = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'users'"
            ).fetchone()
            email_column = "u.email" if has_users else "NULL"
            join = "LEFT JOIN users u ON u.id = e.actor_user_id" if has_users else ""
            rows = connection.execute(
                f"""
                SELECT e.*, {email_column} AS actor_email
                FROM audit_events e {join}
                {where}
                ORDER BY e.created_at DESC, e.rowid DESC
                LIMIT ?
                """,
                (*params, limit),
            ).fetchall()
        finally:
            connection.close()
        return [self._row_to_event(row) for row in rows]

    @staticmethod
    def _row_to_event(row) -> dict:
        return {
            "id": row["id"],
            "created_at": row["created_at"],
            "action": row["action"],
            "actor_user_id": row["actor_user_id"],
            "actor_email": row["actor_email"],
            "target_type": row["target_type"],
            "target_id": row["target_id"],
            "ip": row["ip"],
            "details": json.loads(row["details_json"] or "{}"),
        }
