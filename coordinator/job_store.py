import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


# SQLite-backed queue and job history. The store owns lifecycle transitions and
# exposes plain dicts so FastAPI schemas, tests, and the frontend stay decoupled
# from sqlite3 row objects.
def _now_iso():
    return datetime.now(UTC).isoformat()


class JobStore:
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
                CREATE TABLE IF NOT EXISTS annotation_jobs (
                    id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    current_step TEXT NOT NULL DEFAULT 'queued',
                    request_json TEXT NOT NULL,
                    result_json TEXT,
                    error TEXT,
                    annotation_persisted INTEGER NOT NULL DEFAULT 0,
                    annotation_error TEXT,
                    output_path TEXT,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT
                )
                """
            )
            self._ensure_column(connection, "current_step", "TEXT NOT NULL DEFAULT 'queued'")
            self._ensure_column(
                connection,
                "annotation_persisted",
                "INTEGER NOT NULL DEFAULT 0",
            )
            self._ensure_column(connection, "annotation_error", "TEXT")
            self._ensure_column(connection, "batch_id", "TEXT")

    def _ensure_column(self, connection, column_name, column_type):
        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(annotation_jobs)").fetchall()
        }
        if column_name not in columns:
            connection.execute(
                f"ALTER TABLE annotation_jobs ADD COLUMN {column_name} {column_type}"
            )

    def create_job(self, request: dict[str, Any], batch_id=None):
        job_id = str(uuid.uuid4())
        created_at = _now_iso()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO annotation_jobs (
                    id, status, current_step, request_json, batch_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (job_id, "queued", "queued", json.dumps(request), batch_id, created_at),
            )
        return self.get_job(job_id)

    def get_job(self, job_id):
        with self._connect() as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                "SELECT * FROM annotation_jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_job(row)

    def mark_running(self, job_id):
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE annotation_jobs
                SET status = ?, current_step = ?, started_at = COALESCE(started_at, ?)
                WHERE id = ?
                """,
                ("running", "running", _now_iso(), job_id),
            )

    def mark_step(self, job_id, current_step):
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE annotation_jobs
                SET current_step = ?
                WHERE id = ?
                """,
                (current_step, job_id),
            )

    def mark_completed(self, job_id, result: dict[str, Any], output_path=None):
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE annotation_jobs
                SET status = ?, current_step = ?, result_json = ?, output_path = ?, finished_at = ?
                WHERE id = ?
                """,
                (
                    "completed",
                    "completed",
                    json.dumps(result),
                    output_path,
                    _now_iso(),
                    job_id,
                ),
            )

    def mark_failed(self, job_id, error):
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE annotation_jobs
                SET status = ?, current_step = ?, error = ?, finished_at = ?
                WHERE id = ?
                """,
                ("failed", "failed", str(error), _now_iso(), job_id),
            )

    def mark_annotation_persisted(self, job_id):
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE annotation_jobs
                SET annotation_persisted = ?, annotation_error = ?
                WHERE id = ?
                """,
                (1, None, job_id),
            )

    def mark_annotation_error(self, job_id, error):
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE annotation_jobs
                SET annotation_persisted = ?, annotation_error = ?
                WHERE id = ?
                """,
                (0, str(error), job_id),
            )

    def mark_interrupted_running_jobs(self, error):
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE annotation_jobs
                SET status = ?, current_step = ?, error = ?, finished_at = ?
                WHERE status = ?
                """,
                ("failed", "failed", str(error), _now_iso(), "running"),
            )
            return cursor.rowcount

    def clear_finished_jobs(self):
        with self._connect() as connection:
            cursor = connection.execute(
                """
                DELETE FROM annotation_jobs
                WHERE status IN (?, ?)
                """,
                ("completed", "failed"),
            )
            return cursor.rowcount

    def claim_next_queued_job(self):
        with self._connect() as connection:
            connection.row_factory = sqlite3.Row
            # BEGIN IMMEDIATE serializes claims across threads/processes using
            # the same database file. The extra running-job check preserves the
            # project invariant that only one heavy annotation run happens at a
            # time.
            connection.execute("BEGIN IMMEDIATE")
            running = connection.execute(
                "SELECT id FROM annotation_jobs WHERE status = ? LIMIT 1",
                ("running",),
            ).fetchone()
            if running is not None:
                connection.commit()
                return None

            queued = connection.execute(
                """
                SELECT id
                FROM annotation_jobs
                WHERE status = ?
                ORDER BY created_at ASC
                LIMIT 1
                """,
                ("queued",),
            ).fetchone()
            if queued is None:
                connection.commit()
                return None

            connection.execute(
                """
                UPDATE annotation_jobs
                SET status = ?, current_step = ?, started_at = COALESCE(started_at, ?)
                WHERE id = ?
                """,
                ("running", "running", _now_iso(), queued["id"]),
            )
            connection.commit()
        return self.get_job(queued["id"])

    def list_jobs(self, order="newest", limit=100, batch_id=None):
        if order == "queue":
            order_clause = """
                CASE status
                    WHEN 'running' THEN 0
                    WHEN 'queued' THEN 1
                    WHEN 'failed' THEN 2
                    WHEN 'completed' THEN 3
                    ELSE 4
                END,
                created_at ASC
            """
        else:
            order_clause = "created_at DESC"

        where_clause = ""
        params: list[Any] = []
        if batch_id is not None:
            where_clause = "WHERE batch_id = ?"
            params.append(batch_id)
        params.append(limit)

        with self._connect() as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                f"""
                SELECT *
                FROM annotation_jobs
                {where_clause}
                ORDER BY {order_clause}
                LIMIT ?
                """,
                params,
            ).fetchall()

        return self._add_queue_positions([self._row_to_job(row) for row in rows])

    def list_jobs_by_batch(self, batch_id, limit=5000):
        with self._connect() as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                """
                SELECT *
                FROM annotation_jobs
                WHERE batch_id = ?
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (batch_id, limit),
            ).fetchall()
        return [self._row_to_job(row) for row in rows]

    def queue_summary(self):
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT status, COUNT(*) AS count
                FROM annotation_jobs
                GROUP BY status
                """
            ).fetchall()
        counts = {status: count for status, count in rows}
        return {
            "queued": counts.get("queued", 0),
            "running": counts.get("running", 0),
            "completed": counts.get("completed", 0),
            "failed": counts.get("failed", 0),
        }

    def health(self):
        with self._connect() as connection:
            connection.execute("SELECT 1").fetchone()
        return {"status": "ok", "path": str(self.db_path)}

    def _row_to_job(self, row):
        result = json.loads(row["result_json"]) if row["result_json"] else None
        return {
            "id": row["id"],
            "status": row["status"],
            "current_step": row["current_step"],
            "batch_id": row["batch_id"],
            "request": json.loads(row["request_json"]),
            "result": result,
            "error": row["error"],
            "annotation_persisted": bool(row["annotation_persisted"]),
            "annotation_error": row["annotation_error"],
            "output_path": row["output_path"],
            "created_at": row["created_at"],
            "started_at": row["started_at"],
            "finished_at": row["finished_at"],
            "result_available": result is not None,
            "queue_position": None,
        }

    def _add_queue_positions(self, jobs):
        position = 1
        for job in sorted(jobs, key=lambda item: item["created_at"]):
            if job["status"] == "queued":
                job["queue_position"] = position
                position += 1
            else:
                job["queue_position"] = None
        return jobs
