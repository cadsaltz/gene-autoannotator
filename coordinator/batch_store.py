import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _now_iso():
    return datetime.now(UTC).isoformat()


class BatchStore:
    def __init__(self, db_path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self):
        return sqlite3.connect(self.db_path)

    def _initialize(self):
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS annotation_batches (
                    id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    profile TEXT,
                    organism TEXT,
                    strain TEXT,
                    options_json TEXT NOT NULL,
                    input_summary_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )

    def create_batch(
        self,
        *,
        profile: str | None = None,
        organism: str | None = None,
        strain: str | None = None,
        options: dict[str, Any] | None = None,
        input_summary: dict[str, Any] | None = None,
        status: str = "queued",
    ):
        batch_id = str(uuid.uuid4())
        created_at = _now_iso()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO annotation_batches (
                    id, status, profile, organism, strain,
                    options_json, input_summary_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    batch_id,
                    status,
                    profile,
                    organism,
                    strain,
                    json.dumps(options or {}),
                    json.dumps(input_summary or {}),
                    created_at,
                ),
            )
        return self.get_batch(batch_id)

    def get_batch(self, batch_id):
        with self._connect() as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                "SELECT * FROM annotation_batches WHERE id = ?",
                (batch_id,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_batch(row)

    def _row_to_batch(self, row):
        return {
            "id": row["id"],
            "status": row["status"],
            "profile": row["profile"],
            "organism": row["organism"],
            "strain": row["strain"],
            "options": json.loads(row["options_json"]),
            "input_summary": json.loads(row["input_summary_json"]),
            "created_at": row["created_at"],
        }
