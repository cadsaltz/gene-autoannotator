import pytest

from backend.job_store import JobStore
from tests.auth_helpers import signed_in_client, worker_headers

JOB = {"profile": "mtb-h37rv", "locus": "Rv0001"}
REGISTER = {
    "worker_name": "w",
    "hostname": "h",
    "agent_version": "t",
    "total_memory_bytes": 1,
    "dedicated_memory_bytes": 1,
    "max_slots": 1,
    "ollama_models": [],
}


@pytest.fixture(autouse=True)
def isolate_profile_and_mongo_env(tmp_path, monkeypatch):
    monkeypatch.setenv("PROFILES_DIR", str(tmp_path / "profiles"))
    monkeypatch.delenv("MONGO_URI", raising=False)
    monkeypatch.delenv("MONGODB_URI", raising=False)


def _store_with_job(tmp_path):
    store = JobStore(tmp_path / "jobs.sqlite3")
    job_id = store.create_job(dict(JOB))["id"]
    return store, job_id


def test_stale_fail_from_worker_a_leaves_worker_b_job_running(tmp_path):
    store, job_id = _store_with_job(tmp_path)
    store.assign_job_to_worker("worker-a")
    assert store.fail_job(job_id, "ollama down", retryable=True, worker_id="worker-a") is True
    assert store.assign_job_to_worker("worker-b")["id"] == job_id

    assert store.fail_job(job_id, "ollama down", retryable=True, worker_id="worker-a") is False
    assert store.fail_job(job_id, "ollama down", retryable=False, worker_id="worker-a") is False

    job = store.get_job(job_id)
    assert job["status"] == "running"
    assert job["worker_id"] == "worker-b"
    assert job["attempts"] == 2


def test_duplicate_retryable_fail_does_not_double_count_attempts(tmp_path):
    store, job_id = _store_with_job(tmp_path)
    store.assign_job_to_worker("worker-a")

    assert store.fail_job(job_id, "ollama down", retryable=True, worker_id="worker-a") is True
    assert store.fail_job(job_id, "ollama down", retryable=True, worker_id="worker-a") is False

    job = store.get_job(job_id)
    assert job["status"] == "queued"
    assert job["attempts"] == 1


def test_fail_without_worker_id_still_works_for_old_workers(tmp_path):
    store, job_id = _store_with_job(tmp_path)
    store.assign_job_to_worker("worker-a")

    assert store.fail_job(job_id, "bad locus", retryable=False) is True

    assert store.get_job(job_id)["status"] == "failed"


def test_fail_without_worker_id_ignores_non_running_job(tmp_path):
    store, job_id = _store_with_job(tmp_path)

    assert store.fail_job(job_id, "bad locus", retryable=False) is False

    assert store.get_job(job_id)["status"] == "queued"


def test_complete_from_stale_worker_is_refused(tmp_path):
    store, job_id = _store_with_job(tmp_path)
    store.assign_job_to_worker("worker-a")
    store.fail_job(job_id, "ollama down", retryable=True, worker_id="worker-a")
    store.assign_job_to_worker("worker-b")

    assert store.complete_if_running(job_id, {"x": "a"}, worker_id="worker-a") is False
    assert store.get_job(job_id)["status"] == "running"
    assert store.complete_if_running(job_id, {"x": "b"}, worker_id="worker-b") is True
    assert store.get_job(job_id)["result"] == {"x": "b"}


def test_complete_without_worker_id_still_works_for_old_workers(tmp_path):
    store, job_id = _store_with_job(tmp_path)
    store.assign_job_to_worker("worker-a")

    assert store.complete_if_running(job_id, {"x": 1}) is True


def _register_and_claim(client, headers, name):
    body = {**REGISTER, "worker_name": name, "hostname": name}
    worker_id = client.post("/workers/register", headers=headers, json=body).json()["worker_id"]
    claim = client.post(f"/workers/{worker_id}/claim", headers=headers, json={"free_slots": 1})
    assert claim.status_code == 200
    return worker_id, claim.json()["job_id"]


def test_api_stale_fail_is_204_no_op_and_logged(tmp_path, caplog):
    import logging

    alice = signed_in_client(tmp_path, email="alice@example.com")
    headers = worker_headers()
    job_id = alice.post("/jobs", json=JOB).json()["job_id"]
    worker_a, claimed = _register_and_claim(alice, headers, "worker-a")
    assert claimed == job_id
    fail_body = {"error": "ollama down", "retryable": True, "worker_id": worker_a}
    assert alice.post(f"/jobs/{job_id}/fail", headers=headers, json=fail_body).status_code == 204
    worker_b, reclaimed = _register_and_claim(alice, headers, "worker-b")
    assert reclaimed == job_id
    assert worker_b != worker_a

    caplog.set_level(logging.INFO, logger="backend.api")
    stale = alice.post(f"/jobs/{job_id}/fail", headers=headers, json=fail_body)
    stale_complete = alice.post(
        f"/jobs/{job_id}/complete",
        headers=headers,
        json={"result": {"annotation": {"gene_id": "stale"}}, "worker_id": worker_a},
    )

    assert stale.status_code == 204
    assert stale_complete.status_code == 204
    job = alice.get(f"/jobs/{job_id}").json()
    assert job["status"] == "running"
    assert job["result"] is None
    messages = [record.getMessage() for record in caplog.records]
    assert any("Ignored fail" in message and job_id in message for message in messages)
    assert any("Ignored complete" in message and job_id in message for message in messages)
