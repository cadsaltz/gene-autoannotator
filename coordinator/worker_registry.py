import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path


def _now_iso():
    return datetime.now(UTC).isoformat()


class WorkerRegistry:
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
                CREATE TABLE IF NOT EXISTS workers (
                    id TEXT PRIMARY KEY,
                    worker_name TEXT NOT NULL,
                    hostname TEXT NOT NULL,
                    agent_version TEXT NOT NULL,
                    total_memory_bytes INTEGER NOT NULL DEFAULT 0,
                    dedicated_memory_bytes INTEGER NOT NULL DEFAULT 0,
                    max_slots INTEGER NOT NULL DEFAULT 0,
                    active_jobs INTEGER NOT NULL DEFAULT 0,
                    free_slots INTEGER NOT NULL DEFAULT 0,
                    memory_available_bytes INTEGER NOT NULL DEFAULT 0,
                    cpu_percent REAL NOT NULL DEFAULT 0,
                    state TEXT NOT NULL DEFAULT 'provisioning',
                    ollama_models TEXT,
                    last_heartbeat_at TEXT,
                    registered_at TEXT NOT NULL
                )
                """
            )

    def register(self, payload):
        with self._connect() as connection:
            connection.row_factory = sqlite3.Row
            existing = connection.execute(
                "SELECT id FROM workers WHERE hostname = ? AND worker_name = ?",
                (payload["hostname"], payload["worker_name"]),
            ).fetchone()
            worker_id = existing["id"] if existing else str(uuid.uuid4())
            now = _now_iso()
            max_slots = payload["max_slots"]
            connection.execute(
                """
                INSERT INTO workers (
                    id, worker_name, hostname, agent_version,
                    total_memory_bytes, dedicated_memory_bytes, max_slots,
                    active_jobs, free_slots, memory_available_bytes, cpu_percent,
                    state, ollama_models, last_heartbeat_at, registered_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    worker_name = excluded.worker_name,
                    agent_version = excluded.agent_version,
                    total_memory_bytes = excluded.total_memory_bytes,
                    dedicated_memory_bytes = excluded.dedicated_memory_bytes,
                    max_slots = excluded.max_slots,
                    free_slots = excluded.free_slots,
                    ollama_models = excluded.ollama_models,
                    state = excluded.state,
                    last_heartbeat_at = excluded.last_heartbeat_at
                """,
                (
                    worker_id, payload["worker_name"], payload["hostname"], payload["agent_version"],
                    payload["total_memory_bytes"], payload["dedicated_memory_bytes"], max_slots,
                    0, max_slots, 0, 0.0,
                    "ready", json.dumps(payload.get("ollama_models", [])), now, now,
                ),
            )
            return worker_id

    def heartbeat(self, worker_id, payload):
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE workers
                SET active_jobs = ?, free_slots = ?, memory_available_bytes = ?,
                    cpu_percent = ?, state = ?, last_heartbeat_at = ?
                WHERE id = ?
                """,
                (
                    payload["active_jobs"], payload["free_slots"], payload["memory_available_bytes"],
                    payload["cpu_percent"], payload["state"], _now_iso(), worker_id,
                ),
            )
            return cursor.rowcount > 0

    def set_state(self, worker_id, state):
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE workers SET state = ? WHERE id = ?", (state, worker_id)
            )
            return cursor.rowcount > 0

    def get(self, worker_id, *, offline_after_seconds=60):
        with self._connect() as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                "SELECT * FROM workers WHERE id = ?", (worker_id,)
            ).fetchone()
        return self._row_to_worker(row, offline_after_seconds=offline_after_seconds) if row else None

    def list_workers(self, *, offline_after_seconds=60):
        with self._connect() as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                "SELECT * FROM workers ORDER BY registered_at ASC"
            ).fetchall()
        return [
            self._row_to_worker(row, offline_after_seconds=offline_after_seconds) for row in rows
        ]

    def list_ready_workers(self, *, offline_after_seconds=60):
        return [
            worker
            for worker in self.list_workers(offline_after_seconds=offline_after_seconds)
            if worker["state"] == "ready" and worker["free_slots"] > 0
        ]

    def summary(self, *, offline_after_seconds=60):
        workers = self.list_workers(offline_after_seconds=offline_after_seconds)
        online = [w for w in workers if w["state"] != "offline"]
        return {
            "connected": len(online),
            "total": len(workers),
            "used_slots": sum(w["active_jobs"] for w in online),
            "available_slots": sum(
                w["free_slots"] for w in online if w["state"] in ("ready", "provisioning")
            ),
            "total_slots": sum(w["max_slots"] for w in online),
            "states": {
                state: sum(1 for w in workers if w["state"] == state)
                for state in ("ready", "provisioning", "draining", "offline")
            },
        }

    def _row_to_worker(self, row, *, offline_after_seconds=60):
        state = row["state"]
        last = row["last_heartbeat_at"]
        if state != "draining" and last is not None:
            age = (datetime.now(UTC) - datetime.fromisoformat(last)).total_seconds()
            if age > offline_after_seconds:
                state = "offline"
        return {
            "id": row["id"],
            "worker_name": row["worker_name"],
            "hostname": row["hostname"],
            "agent_version": row["agent_version"],
            "total_memory_bytes": row["total_memory_bytes"],
            "dedicated_memory_bytes": row["dedicated_memory_bytes"],
            "max_slots": row["max_slots"],
            "active_jobs": row["active_jobs"],
            "free_slots": row["free_slots"],
            "memory_available_bytes": row["memory_available_bytes"],
            "cpu_percent": row["cpu_percent"],
            "state": state,
            "ollama_models": json.loads(row["ollama_models"]) if row["ollama_models"] else [],
            "last_heartbeat_at": last,
            "registered_at": row["registered_at"],
        }
