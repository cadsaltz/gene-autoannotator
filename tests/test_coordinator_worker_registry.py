import time

from coordinator.worker_registry import WorkerRegistry


def _register_payload(**overrides):
    payload = {
        "worker_name": "laptop-a",
        "hostname": "laptop-a",
        "agent_version": "0.1.0",
        "total_memory_bytes": 64_000_000_000,
        "dedicated_memory_bytes": 42_000_000_000,
        "max_slots": 2,
        "ollama_models": ["llama3:8b"],
    }
    payload.update(overrides)
    return payload


def test_register_is_idempotent_by_hostname_and_name(tmp_path):
    registry = WorkerRegistry(tmp_path / "jobs.sqlite3")
    first = registry.register(_register_payload())
    second = registry.register(_register_payload(agent_version="0.2.0"))
    assert first == second
    workers = registry.list_workers()
    assert len(workers) == 1
    assert workers[0]["agent_version"] == "0.2.0"


def test_heartbeat_updates_counts(tmp_path):
    registry = WorkerRegistry(tmp_path / "jobs.sqlite3")
    worker_id = registry.register(_register_payload())
    registry.heartbeat(
        worker_id,
        {
            "active_jobs": 1,
            "free_slots": 1,
            "memory_available_bytes": 10_000_000_000,
            "cpu_percent": 5.0,
            "state": "ready",
        },
    )
    worker = registry.get(worker_id)
    assert worker["active_jobs"] == 1
    assert worker["free_slots"] == 1


def test_offline_derived_from_stale_heartbeat(tmp_path):
    registry = WorkerRegistry(tmp_path / "jobs.sqlite3")
    worker_id = registry.register(_register_payload())
    time.sleep(0.01)
    workers = registry.list_workers(offline_after_seconds=0)
    assert workers[0]["state"] == "offline"
