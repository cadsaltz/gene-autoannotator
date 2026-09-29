from datetime import UTC, datetime, timedelta

import pytest

from backend.access import BOOTSTRAP_ADMIN_EMAIL
from backend.job_store import JobStore
from tests.auth_helpers import second_client, signed_in_client, worker_headers

JOB = {"profile": "mtb-h37rv", "locus": "Rv0001"}
BATCH = {
    "profile": "mtb-h37rv",
    "entries": [{"input": "Rv0001"}, {"input": "Rv0002"}],
    "allow_online_name_lookup": False,
}
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


def _job_store(client) -> JobStore:
    return JobStore(client.auth_store.db_path)


def _submit(client) -> str:
    response = client.post("/jobs", json=JOB)
    assert response.status_code == 201
    return response.json()["job_id"]


def _claim(client) -> str:
    headers = worker_headers()
    worker_id = client.post("/workers/register", headers=headers, json=REGISTER).json()["worker_id"]
    claim = client.post(f"/workers/{worker_id}/claim", headers=headers, json={"free_slots": 1})
    assert claim.status_code == 200
    return claim.json()["job_id"]


def test_owner_cancels_queued_job(tmp_path):
    alice = signed_in_client(tmp_path, email="alice@example.com")
    job_id = _submit(alice)

    response = alice.post(f"/jobs/{job_id}/cancel")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == job_id
    assert body["status"] == "cancelled"
    assert body["current_step"] == "cancelled"
    assert body["error"] == "Cancelled by user"
    assert body["finished_at"]
    assert "submitted_by_user_id" not in body
    assert "output_path" not in body
    assert alice.get(f"/jobs/{job_id}").json()["status"] == "cancelled"


def test_other_user_cannot_cancel(tmp_path):
    alice = signed_in_client(tmp_path, email="alice@example.com")
    bob = second_client(alice, email="bob@example.com")
    job_id = _submit(alice)

    assert bob.post(f"/jobs/{job_id}/cancel").status_code == 404
    assert alice.get(f"/jobs/{job_id}").json()["status"] == "queued"


def test_cancel_unknown_job_is_404(tmp_path):
    alice = signed_in_client(tmp_path, email="alice@example.com")
    assert alice.post("/jobs/does-not-exist/cancel").status_code == 404


def test_cancel_requires_sign_in(tmp_path):
    alice = signed_in_client(tmp_path, email="alice@example.com")
    job_id = _submit(alice)
    alice.post("/auth/logout")
    assert alice.post(f"/jobs/{job_id}/cancel").status_code == 401


def test_admin_cancels_any_job(tmp_path):
    alice = signed_in_client(tmp_path, email="alice@example.com")
    admin = second_client(alice, email=BOOTSTRAP_ADMIN_EMAIL)
    job_id = _submit(alice)

    response = admin.post(f"/jobs/{job_id}/cancel")

    assert response.status_code == 200
    assert response.json()["error"] == "Cancelled by admin"
    assert response.json()["submitted_by_user_id"]


def test_cancel_terminal_job_is_409(tmp_path):
    alice = signed_in_client(tmp_path, email="alice@example.com")
    cancelled = _submit(alice)
    assert alice.post(f"/jobs/{cancelled}/cancel").status_code == 200
    assert alice.post(f"/jobs/{cancelled}/cancel").status_code == 409

    completed = _submit(alice)
    store = _job_store(alice)
    store.mark_running(completed)
    store.mark_completed(completed, {})
    assert alice.post(f"/jobs/{completed}/cancel").status_code == 409
    assert alice.get(f"/jobs/{completed}").json()["status"] == "completed"


def test_owner_cancels_running_job(tmp_path):
    alice = signed_in_client(tmp_path, email="alice@example.com")
    job_id = _submit(alice)
    assert _claim(alice) == job_id

    response = alice.post(f"/jobs/{job_id}/cancel")

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    assert _job_store(alice).get_job(job_id)["lease_expires_at"] is None


def test_cancelled_running_job_rejects_progress_and_complete(tmp_path):
    alice = signed_in_client(tmp_path, email="alice@example.com")
    job_id = _submit(alice)
    headers = worker_headers()
    assert _claim(alice) == job_id
    alice.post(f"/jobs/{job_id}/cancel")

    progress = alice.patch(f"/jobs/{job_id}/progress", headers=headers, json={"current_step": "x"})
    assert progress.status_code == 409
    assert progress.json() == {"detail": "Job cancelled", "cancelled": True}

    complete = alice.post(
        f"/jobs/{job_id}/complete",
        headers=headers,
        json={"result": {"annotation": {"gene_id": "Rv0001"}}},
    )
    assert complete.status_code == 204

    job = alice.get(f"/jobs/{job_id}").json()
    assert job["status"] == "cancelled"
    assert job["current_step"] == "cancelled"
    assert job["result"] is None
    assert job["annotation_persisted"] is False


def test_fail_on_cancelled_job_is_a_no_op(tmp_path):
    alice = signed_in_client(tmp_path, email="alice@example.com")
    job_id = _submit(alice)
    assert _claim(alice) == job_id
    alice.post(f"/jobs/{job_id}/cancel")

    for retryable in (True, False):
        response = alice.post(
            f"/jobs/{job_id}/fail",
            headers=worker_headers(),
            json={"error": "boom", "retryable": retryable},
        )
        assert response.status_code == 204

    job = alice.get(f"/jobs/{job_id}").json()
    assert job["status"] == "cancelled"
    assert job["error"] == "Cancelled by user"


def test_claim_skips_cancelled_jobs(tmp_path):
    alice = signed_in_client(tmp_path, email="alice@example.com")
    cancelled = _submit(alice)
    kept = _submit(alice)
    alice.post(f"/jobs/{cancelled}/cancel")

    assert _claim(alice) == kept

    headers = worker_headers()
    worker_id = alice.post("/workers/register", headers=headers, json=REGISTER).json()["worker_id"]
    again = alice.post(f"/workers/{worker_id}/claim", headers=headers, json={"free_slots": 1})
    assert again.status_code == 204


def test_cancel_frees_active_quota_slot(tmp_path, monkeypatch):
    monkeypatch.setenv("USER_MAX_ACTIVE_JOBS", "1")
    alice = signed_in_client(tmp_path, email="alice@example.com")
    job_id = _submit(alice)
    assert alice.post("/jobs", json=JOB).status_code == 429

    alice.post(f"/jobs/{job_id}/cancel")

    assert alice.get("/jobs/queue-status").json()["your_active"] == 0
    assert alice.post("/jobs", json=JOB).status_code == 201


def test_queue_summaries_count_cancelled(tmp_path):
    alice = signed_in_client(tmp_path, email="alice@example.com")
    batch = alice.post("/batches", json=BATCH).json()
    alice.post(f"/jobs/{batch['job_ids'][0]}/cancel")

    assert alice.get("/jobs").json()["queue"] == {
        "queued": 1, "running": 0, "completed": 0, "failed": 0, "cancelled": 1,
    }
    assert alice.get(f"/batches/{batch['batch_id']}").json()["queue"] == {
        "queued": 1, "running": 0, "completed": 0, "failed": 0, "cancelled": 1,
    }


def test_clear_history_removes_cancelled_jobs(tmp_path):
    alice = signed_in_client(tmp_path, email="alice@example.com")
    admin = second_client(alice, email=BOOTSTRAP_ADMIN_EMAIL)
    cancelled = _submit(alice)
    queued = _submit(alice)
    alice.post(f"/jobs/{cancelled}/cancel")

    assert admin.delete("/jobs/history").json() == {"deleted": 1}
    assert [j["id"] for j in admin.get("/jobs").json()["jobs"]] == [queued]


def test_store_cancel_job_returns_previous_status(tmp_path):
    store = JobStore(tmp_path / "jobs.sqlite3")
    queued = store.create_job(dict(JOB), submitted_by_user_id="u1")["id"]
    running = store.create_job(dict(JOB), submitted_by_user_id="u1")["id"]
    store.mark_running(running)
    done = store.create_job(dict(JOB), submitted_by_user_id="u1")["id"]
    store.mark_running(done)
    store.mark_completed(done, {})

    assert store.cancel_job(queued) == "queued"
    assert store.cancel_job(running, by="admin") == "running"
    assert store.cancel_job(queued) is None
    assert store.cancel_job(done) is None
    assert store.cancel_job("missing") is None

    assert store.get_job(queued)["error"] == "Cancelled by user"
    assert store.get_job(running)["error"] == "Cancelled by admin"
    assert store.get_job(done)["status"] == "completed"
    assert store.count_active_for_user("u1") == 0


def test_store_cancelled_job_is_never_requeued_or_revived(tmp_path):
    store = JobStore(tmp_path / "jobs.sqlite3")
    job_id = store.create_job(dict(JOB))["id"]
    assert store.assign_job_to_worker("w1", lease_seconds=60)["id"] == job_id
    store.cancel_job(job_id)

    past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    with store._connect() as connection:
        connection.execute(
            "UPDATE annotation_jobs SET lease_expires_at = ? WHERE id = ?", (past, job_id)
        )
    assert store.requeue_expired_leases(max_attempts=3) == {"requeued": [], "failed": []}

    store.renew_lease(job_id)
    assert store.renew_worker_leases("w1") == 0
    assert store.complete_if_running(job_id, {"x": 1}) is False
    store.fail_job(job_id, "boom", retryable=True)
    store.fail_job(job_id, "boom", retryable=False)
    assert store.assign_job_to_worker("w2") is None

    job = store.get_job(job_id)
    assert job["status"] == "cancelled"
    assert job["lease_expires_at"] == past
    assert job["error"] == "Cancelled by user"
    assert store.queue_summary()["cancelled"] == 1
