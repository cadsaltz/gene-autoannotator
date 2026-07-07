import json
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any


# SQLite-backed queue and job history. The store owns lifecycle transitions and
# exposes plain dicts so FastAPI schemas, tests, and the frontend stay decoupled
# from sqlite3 row objects.
def _now_iso():
    return datetime.now(UTC).isoformat()


def _iso_in(seconds):
    return (datetime.now(UTC) + timedelta(seconds=seconds)).isoformat()


class JobStore:
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
                    finished_at TEXT,
                    worker_id TEXT,
                    lease_expires_at TEXT,
                    attempts INTEGER NOT NULL DEFAULT 0
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
            self._ensure_column(connection, "worker_id", "TEXT")
            self._ensure_column(connection, "lease_expires_at", "TEXT")
            self._ensure_column(connection, "attempts", "INTEGER NOT NULL DEFAULT 0")

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
            # the same database file.
            connection.execute("BEGIN IMMEDIATE")
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

    def assign_job_to_worker(self, worker_id, *, lease_seconds=31536000):
        with self._connect() as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("BEGIN IMMEDIATE")
            queued = connection.execute(
                """
                SELECT id FROM annotation_jobs
                WHERE status = 'queued'
                ORDER BY created_at ASC
                LIMIT 1
                """
            ).fetchone()
            if queued is None:
                connection.commit()
                return None
            connection.execute(
                """
                UPDATE annotation_jobs
                SET status = 'running', current_step = 'running', worker_id = ?,
                    lease_expires_at = ?, attempts = attempts + 1,
                    started_at = COALESCE(started_at, ?)
                WHERE id = ?
                """,
                (worker_id, _iso_in(lease_seconds), _now_iso(), queued["id"]),
            )
            connection.commit()
        return self.get_job(queued["id"])

    def renew_lease(self, job_id, *, lease_seconds=31536000):
        with self._connect() as connection:
            connection.execute(
                "UPDATE annotation_jobs SET lease_expires_at = ? WHERE id = ? AND status = 'running'",
                (_iso_in(lease_seconds), job_id),
            )

    def requeue_expired_leases(self, *, max_attempts=3):
        now = _now_iso()
        requeued, failed = [], []
        with self._connect() as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("BEGIN IMMEDIATE")
            expired = connection.execute(
                """
                SELECT id, attempts FROM annotation_jobs
                WHERE status = 'running'
                  AND lease_expires_at IS NOT NULL
                  AND lease_expires_at < ?
                """,
                (now,),
            ).fetchall()
            for row in expired:
                if row["attempts"] >= max_attempts:
                    connection.execute(
                        """
                        UPDATE annotation_jobs
                        SET status = 'failed', current_step = 'failed',
                            error = 'Lease expired after max attempts', finished_at = ?,
                            worker_id = NULL, lease_expires_at = NULL
                        WHERE id = ?
                        """,
                        (now, row["id"]),
                    )
                    failed.append(row["id"])
                else:
                    connection.execute(
                        """
                        UPDATE annotation_jobs
                        SET status = 'queued', current_step = 'queued',
                            worker_id = NULL, lease_expires_at = NULL, started_at = NULL
                        WHERE id = ?
                        """,
                        (row["id"],),
                    )
                    requeued.append(row["id"])
            connection.commit()
        return {"requeued": requeued, "failed": failed}

    def complete_if_running(self, job_id, result, output_path=None):
        with self._connect() as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT status FROM annotation_jobs WHERE id = ?", (job_id,)
            ).fetchone()
            if row is None or row["status"] != "running":
                connection.commit()
                return False
            connection.execute(
                """
                UPDATE annotation_jobs
                SET status = 'completed', current_step = 'completed', result_json = ?,
                    output_path = ?, finished_at = ?, lease_expires_at = NULL
                WHERE id = ?
                """,
                (json.dumps(result), output_path, _now_iso(), job_id),
            )
            connection.commit()
        return True

    def fail_job(self, job_id, error, *, retryable=False, max_attempts=3):
        with self._connect() as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT status, attempts FROM annotation_jobs WHERE id = ?", (job_id,)
            ).fetchone()
            if row is None or row["status"] in ("completed", "failed"):
                connection.commit()
                return
            if retryable and row["attempts"] < max_attempts:
                connection.execute(
                    """
                    UPDATE annotation_jobs
                    SET status = 'queued', current_step = 'queued',
                        worker_id = NULL, lease_expires_at = NULL, started_at = NULL
                    WHERE id = ?
                    """,
                    (job_id,),
                )
            else:
                connection.execute(
                    """
                    UPDATE annotation_jobs
                    SET status = 'failed', current_step = 'failed', error = ?,
                        finished_at = ?, worker_id = NULL, lease_expires_at = NULL
                    WHERE id = ?
                    """,
                    (str(error), _now_iso(), job_id),
                )
            connection.commit()

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
            "worker_id": row["worker_id"],
            "lease_expires_at": row["lease_expires_at"],
            "attempts": row["attempts"],
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
