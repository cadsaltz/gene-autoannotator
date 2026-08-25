from fastapi.testclient import TestClient

from backend.annotation_store import InMemoryAnnotationStore
from backend.api import create_app
from backend.job_store import JobStore
from backend.worker_registry import WorkerRegistry


def _make_client(tmp_path):
    db_path = tmp_path / "jobs.sqlite3"
    store = JobStore(db_path)
    registry = WorkerRegistry(db_path)
    app = create_app(
        job_store=store,
        annotation_store=InMemoryAnnotationStore(),
        worker_registry=registry,
        start_worker=False,
        worker_api_token="test-token",
    )
    return TestClient(app), store


def _register(client, headers, *, worker_name, hostname, max_slots):
    response = client.post(
        "/workers/register",
        json={
            "worker_name": worker_name,
            "hostname": hostname,
            "agent_version": "0.1.0",
            "total_memory_bytes": 64_000_000_000,
            "dedicated_memory_bytes": 42_000_000_000,
            "max_slots": max_slots,
            "ollama_models": ["llama3:8b"],
        },
        headers=headers,
    )
    assert response.status_code == 200
    return response.json()["worker_id"]


def _queue_job(store, locus):
    store.create_job(
        {
            "profile": "mtb-h37rv",
            "locus": locus,
            "cache_dir": "./.cache",
            "output_dir": "gen_json",
        }
    )


def test_claim_uses_request_free_slots_when_heartbeat_stale(tmp_path):
    client, store = _make_client(tmp_path)
    headers = {"Authorization": "Bearer test-token"}

    worker_id = _register(client, headers, worker_name="solo", hostname="solo", max_slots=2)
    _queue_job(store, "Rv0099")

    # Simulate a stale heartbeat that still reports zero free slots.
    registry = WorkerRegistry(tmp_path / "jobs.sqlite3")
    registry.heartbeat(
        worker_id,
        {
            "active_jobs": 2,
            "free_slots": 0,
            "memory_available_bytes": 1,
            "cpu_percent": 0.0,
            "state": "ready",
        },
    )

    claim = client.post(
        f"/workers/{worker_id}/claim",
        json={"free_slots": 2},
        headers=headers,
    )
    assert claim.status_code == 200
    assert claim.json()["request"]["locus"] == "Rv0099"


def test_assign_only_when_worker_has_max_free_slots(tmp_path):
    client, store = _make_client(tmp_path)
    headers = {"Authorization": "Bearer test-token"}

    big_worker_id = _register(client, headers, worker_name="big", hostname="big", max_slots=4)
    small_worker_id = _register(client, headers, worker_name="small", hostname="small", max_slots=2)
    _queue_job(store, "Rv0001")

    small_claim = client.post(
        f"/workers/{small_worker_id}/claim",
        json={"free_slots": 2},
        headers=headers,
    )
    assert small_claim.status_code == 204

    big_claim = client.post(
        f"/workers/{big_worker_id}/claim",
        json={"free_slots": 4},
        headers=headers,
    )
    assert big_claim.status_code == 200
    assert big_claim.json()["job_id"]
    assert store.get_job(big_claim.json()["job_id"])["worker_id"] == big_worker_id


def test_both_workers_at_max_free_slots_can_claim(tmp_path):
    client, store = _make_client(tmp_path)
    headers = {"Authorization": "Bearer test-token"}

    worker_a = _register(client, headers, worker_name="a", hostname="a", max_slots=4)
    worker_b = _register(client, headers, worker_name="b", hostname="b", max_slots=4)
    _queue_job(store, "Rv0001")
    _queue_job(store, "Rv0002")

    claim_a = client.post(
        f"/workers/{worker_a}/claim",
        json={"free_slots": 4},
        headers=headers,
    )
    claim_b = client.post(
        f"/workers/{worker_b}/claim",
        json={"free_slots": 4},
        headers=headers,
    )

    assert claim_a.status_code == 200
    assert claim_b.status_code == 200
    assert claim_a.json()["job_id"] != claim_b.json()["job_id"]
