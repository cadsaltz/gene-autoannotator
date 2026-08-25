"""Backend behaviour required by an HPC-primary deploy with no warm laptop."""

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from backend.annotation_store import InMemoryAnnotationStore
from backend.api import DEFAULT_LEASE_SECONDS, create_app
from backend.job_store import JobStore
from backend.worker_registry import WorkerRegistry


@pytest.fixture(autouse=True)
def isolate_backend_env(tmp_path, monkeypatch):
    monkeypatch.setenv("PROFILES_DIR", str(tmp_path / "profiles"))
    monkeypatch.delenv("MONGO_URI", raising=False)
    monkeypatch.delenv("MONGODB_URI", raising=False)
    monkeypatch.delenv("WORKER_CAPACITY_REQUIRED", raising=False)
    monkeypatch.delenv("LEASE_SECONDS", raising=False)


def _make_app(tmp_path, **kwargs):
    db_path = tmp_path / "jobs.sqlite3"
    store = JobStore(db_path)
    registry = WorkerRegistry(db_path)
    app = create_app(
        job_store=store,
        annotation_store=InMemoryAnnotationStore(),
        worker_registry=registry,
        start_worker=False,
        worker_api_token="test-token",
        **kwargs,
    )
    return TestClient(app), store, registry


def _register(client, *, worker_name="hpc", max_slots=1):
    response = client.post(
        "/workers/register",
        json={
            "worker_name": worker_name,
            "hostname": worker_name,
            "agent_version": "0.1.0",
            "total_memory_bytes": 64_000_000_000,
            "dedicated_memory_bytes": 42_000_000_000,
            "max_slots": max_slots,
            "ollama_models": [],
        },
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 200
    return response.json()["worker_id"]


def _submit_job(client):
    return client.post("/jobs", json={"organism": "Custom bacterium", "name": "abc1"})


def test_submission_gate_rejects_when_required_and_no_workers(tmp_path):
    client, _store, _registry = _make_app(tmp_path, worker_capacity_required=True)

    assert _submit_job(client).status_code == 503


def test_worker_capacity_required_env_disables_submission_gate(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKER_CAPACITY_REQUIRED", "0")
    client, _store, _registry = _make_app(tmp_path, worker_capacity_required=True)

    response = _submit_job(client)

    assert response.status_code == 201
    assert response.json()["status"] == "queued"


def test_worker_capacity_required_env_enables_submission_gate(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKER_CAPACITY_REQUIRED", "1")
    client, _store, _registry = _make_app(tmp_path)

    assert _submit_job(client).status_code == 503


def test_queue_summary_requires_worker_token(tmp_path):
    client, _store, _registry = _make_app(tmp_path)

    assert client.get("/jobs/queue-summary").status_code == 401
    authorized = client.get(
        "/jobs/queue-summary",
        headers={"Authorization": "Bearer test-token"},
    )
    assert authorized.status_code == 200
    assert authorized.json() == {"queued": 0}


def test_default_lease_is_six_hours(tmp_path):
    assert DEFAULT_LEASE_SECONDS == 21600

    client, store, _registry = _make_app(tmp_path)
    worker_id = _register(client)
    store.create_job({"profile": "mtb-h37rv", "locus": "Rv0001"})

    claim = client.post(
        f"/workers/{worker_id}/claim",
        json={"free_slots": 1},
        headers={"Authorization": "Bearer test-token"},
    )

    assert claim.status_code == 200
    lease = datetime.fromisoformat(claim.json()["lease_expires_at"])
    remaining = (lease - datetime.now(UTC)).total_seconds()
    assert 21600 - 300 < remaining <= 21600


def test_heartbeat_renews_leases_for_running_jobs(tmp_path):
    client, store, _registry = _make_app(tmp_path)
    worker_id = _register(client)
    store.create_job({"profile": "mtb-h37rv", "locus": "Rv0001"})
    job = store.assign_job_to_worker(worker_id, lease_seconds=-60)
    assert datetime.fromisoformat(job["lease_expires_at"]) < datetime.now(UTC)

    response = client.post(
        f"/workers/{worker_id}/heartbeat",
        json={
            "active_jobs": 1,
            "free_slots": 0,
            "memory_available_bytes": 1,
            "cpu_percent": 0.0,
            "state": "ready",
        },
        headers={"Authorization": "Bearer test-token"},
    )

    assert response.status_code == 200
    renewed = store.get_job(job["id"])
    assert datetime.fromisoformat(renewed["lease_expires_at"]) > datetime.now(UTC)


def test_deregister_removes_worker_from_fleet(tmp_path):
    client, _store, _registry = _make_app(tmp_path)
    worker_id = _register(client)
    headers = {"Authorization": "Bearer test-token"}

    response = client.delete(f"/workers/{worker_id}", headers=headers)

    assert response.status_code == 204
    assert client.get("/workers").json()["workers"] == []
    assert client.delete(f"/workers/{worker_id}", headers=headers).status_code == 404


def test_deregister_requires_worker_token(tmp_path):
    client, _store, _registry = _make_app(tmp_path)
    worker_id = _register(client)

    assert client.delete(f"/workers/{worker_id}").status_code == 401
