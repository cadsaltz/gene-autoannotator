from datetime import UTC, datetime, timedelta

import pytest

from backend.access import BOOTSTRAP_ADMIN_EMAIL
from backend.api import MAX_BATCH_SIZE
from backend.batch_store import BatchStore
from backend.job_store import JobStore
from tests.auth_helpers import second_client, signed_in_client

JOB = {"profile": "mtb-h37rv", "locus": "Rv0001"}
BATCH = {
    "profile": "mtb-h37rv",
    "entries": [{"input": "Rv0001"}, {"input": "Rv0002"}],
    "allow_online_name_lookup": False,
}


@pytest.fixture(autouse=True)
def isolate_profile_and_mongo_env(tmp_path, monkeypatch):
    monkeypatch.setenv("PROFILES_DIR", str(tmp_path / "profiles"))
    monkeypatch.delenv("MONGO_URI", raising=False)
    monkeypatch.delenv("MONGODB_URI", raising=False)


def _job_store(client) -> JobStore:
    return JobStore(client.auth_store.db_path)


def _user_id(client) -> str:
    return client.get("/auth/me").json()["id"]


def test_users_only_list_their_own_jobs(tmp_path):
    alice = signed_in_client(tmp_path, email="alice@example.com")
    bob = second_client(alice, email="bob@example.com")
    alice_job = alice.post("/jobs", json=JOB).json()["job_id"]
    bob.post("/jobs", json=JOB)
    ids = [j["id"] for j in alice.get("/jobs").json()["jobs"]]
    assert ids == [alice_job]


def test_user_cannot_read_other_users_job(tmp_path):
    alice = signed_in_client(tmp_path, email="alice@example.com")
    bob = second_client(alice, email="bob@example.com")
    job_id = alice.post("/jobs", json=JOB).json()["job_id"]
    assert bob.get(f"/jobs/{job_id}").status_code == 404
    assert bob.get(f"/jobs/{job_id}/result").status_code == 404
    assert alice.get(f"/jobs/{job_id}").status_code == 200


def test_admin_lists_all_jobs(tmp_path):
    alice = signed_in_client(tmp_path, email="alice@example.com")
    admin = second_client(alice, email=BOOTSTRAP_ADMIN_EMAIL)
    alice.post("/jobs", json=JOB)
    admin.post("/jobs", json=JOB)
    assert len(admin.get("/jobs").json()["jobs"]) == 2


def test_admin_can_read_any_job(tmp_path):
    alice = signed_in_client(tmp_path, email="alice@example.com")
    admin = second_client(alice, email=BOOTSTRAP_ADMIN_EMAIL)
    job_id = alice.post("/jobs", json=JOB).json()["job_id"]
    response = admin.get(f"/jobs/{job_id}")
    assert response.status_code == 200
    assert response.json()["submitted_by_user_id"] == _user_id(alice)


def test_owner_and_output_path_are_hidden_from_non_admins(tmp_path):
    alice = signed_in_client(tmp_path, email="alice@example.com")
    admin = second_client(alice, email=BOOTSTRAP_ADMIN_EMAIL)
    job_id = alice.post("/jobs", json=JOB).json()["job_id"]
    store = _job_store(alice)
    store.mark_running(job_id)
    store.mark_completed(job_id, {}, output_path="gen_json/gen_Rv0001.json")

    detail = alice.get(f"/jobs/{job_id}").json()
    listed = alice.get("/jobs").json()["jobs"]
    for job in [detail, *listed]:
        assert "submitted_by_user_id" not in job
        assert "output_path" not in job
    assert listed

    admin_detail = admin.get(f"/jobs/{job_id}").json()
    assert admin_detail["output_path"] == "gen_json/gen_Rv0001.json"
    assert admin_detail["submitted_by_user_id"] == _user_id(alice)


def test_non_admin_queue_summary_counts_only_own_jobs(tmp_path):
    alice = signed_in_client(tmp_path, email="alice@example.com")
    bob = second_client(alice, email="bob@example.com")
    admin = second_client(alice, email=BOOTSTRAP_ADMIN_EMAIL)
    alice.post("/jobs", json=JOB)
    store = _job_store(alice)
    bob_running = bob.post("/jobs", json=JOB).json()["job_id"]
    bob_done = bob.post("/jobs", json=JOB).json()["job_id"]
    store.mark_running(bob_running)
    store.mark_running(bob_done)
    store.mark_completed(bob_done, {})
    bob.post("/jobs", json=JOB)

    assert alice.get("/jobs").json()["queue"] == {
        "queued": 1, "running": 0, "completed": 0, "failed": 0,
    }
    assert admin.get("/jobs").json()["queue"] == {
        "queued": 2, "running": 1, "completed": 1, "failed": 0,
    }


def test_queue_position_is_global_for_non_admins(tmp_path):
    alice = signed_in_client(tmp_path, email="alice@example.com")
    bob = second_client(alice, email="bob@example.com")
    bob.post("/jobs", json=JOB)
    alice_job = alice.post("/jobs", json=JOB).json()["job_id"]

    [listed] = alice.get("/jobs").json()["jobs"]
    assert listed["id"] == alice_job
    assert listed["queue_position"] == 2


def test_batch_listing_uses_global_queue_position(tmp_path):
    alice = signed_in_client(tmp_path, email="alice@example.com")
    bob = second_client(alice, email="bob@example.com")
    bob.post("/jobs", json=JOB)
    payload = alice.post("/batches", json=BATCH).json()
    listed = alice.get("/jobs", params={"batch_id": payload["batch_id"]}).json()["jobs"]
    assert sorted(j["queue_position"] for j in listed) == [2, 3]


def test_unowned_legacy_jobs_are_admin_only(tmp_path):
    alice = signed_in_client(tmp_path, email="alice@example.com")
    admin = second_client(alice, email=BOOTSTRAP_ADMIN_EMAIL)
    legacy = _job_store(alice).create_job(dict(JOB))
    assert alice.get("/jobs").json()["jobs"] == []
    assert alice.get(f"/jobs/{legacy['id']}").status_code == 404
    assert [j["id"] for j in admin.get("/jobs").json()["jobs"]] == [legacy["id"]]
    assert admin.get(f"/jobs/{legacy['id']}").status_code == 200


def test_batch_jobs_inherit_batch_owner(tmp_path):
    alice = signed_in_client(tmp_path, email="alice@example.com")
    bob = second_client(alice, email="bob@example.com")
    created = alice.post("/batches", json=BATCH)
    assert created.status_code == 201
    payload = created.json()
    batch_id = payload["batch_id"]
    store = _job_store(alice)
    alice_id = _user_id(alice)
    assert all(
        store.get_job(job_id)["submitted_by_user_id"] == alice_id
        for job_id in payload["job_ids"]
    )
    assert BatchStore(store.db_path).get_batch(batch_id)["submitted_by_user_id"] == alice_id

    alice_listed = alice.get("/jobs", params={"batch_id": batch_id}).json()["jobs"]
    assert sorted(j["id"] for j in alice_listed) == sorted(payload["job_ids"])
    assert bob.get("/jobs", params={"batch_id": batch_id}).json()["jobs"] == []


def test_user_cannot_read_other_users_batch(tmp_path):
    alice = signed_in_client(tmp_path, email="alice@example.com")
    bob = second_client(alice, email="bob@example.com")
    admin = second_client(alice, email=BOOTSTRAP_ADMIN_EMAIL)
    batch_id = alice.post("/batches", json=BATCH).json()["batch_id"]
    assert alice.get(f"/batches/{batch_id}").status_code == 200
    assert bob.get(f"/batches/{batch_id}").status_code == 404
    assert admin.get(f"/batches/{batch_id}").status_code == 200


def test_queue_status_hides_job_details(tmp_path):
    alice = signed_in_client(tmp_path, email="alice@example.com")
    bob = second_client(alice, email="bob@example.com")
    alice.post("/jobs", json=JOB)
    before = alice.get("/jobs/queue-status").json()
    assert before["queued"] == 1
    assert set(before) == {
        "queued", "accepting", "your_active", "your_active_limit",
        "your_today", "your_daily_limit", "batch_limit",
    }

    bob.post("/jobs", json=JOB)
    after = alice.get("/jobs/queue-status").json()
    assert after == {**before, "queued": 2}


def test_queue_status_counts_only_the_callers_jobs(tmp_path):
    alice = signed_in_client(tmp_path, email="alice@example.com")
    bob = second_client(alice, email="bob@example.com")
    alice.post("/jobs", json=JOB)
    alice.post("/jobs", json=JOB)
    bob.post("/jobs", json=JOB)
    body = alice.get("/jobs/queue-status").json()
    assert body == {
        "queued": 3,
        "accepting": True,
        "your_active": 2,
        "your_active_limit": None,
        "your_today": 2,
        "your_daily_limit": None,
        "batch_limit": MAX_BATCH_SIZE,
    }


def test_queue_status_requires_sign_in(tmp_path):
    alice = signed_in_client(tmp_path, email="alice@example.com")
    alice.post("/auth/logout")
    assert alice.get("/jobs/queue-status").status_code == 401


def test_job_store_filters_and_counts_by_owner(tmp_path):
    store = JobStore(tmp_path / "jobs.sqlite3")
    mine_queued = store.create_job(dict(JOB), submitted_by_user_id="u1")
    mine_running = store.create_job(dict(JOB), submitted_by_user_id="u1")
    store.mark_running(mine_running["id"])
    mine_done = store.create_job(dict(JOB), submitted_by_user_id="u1")
    store.mark_completed(mine_done["id"], {})
    store.create_job(dict(JOB), submitted_by_user_id="u2")
    store.create_job(dict(JOB))

    assert mine_queued["submitted_by_user_id"] == "u1"
    assert len(store.list_jobs()) == 5
    assert {j["id"] for j in store.list_jobs(user_id="u1")} == {
        mine_queued["id"], mine_running["id"], mine_done["id"],
    }
    assert store.count_active_for_user("u1") == 2
    assert store.count_active_for_user("u2") == 1
    assert store.count_active_for_user("nobody") == 0

    day_ago = (datetime.now(UTC) - timedelta(hours=24)).isoformat()
    in_future = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    assert store.count_created_since_for_user("u1", day_ago) == 3
    assert store.count_created_since_for_user("u1", in_future) == 0

    assert store.queue_summary(user_id="u1") == {
        "queued": 1, "running": 1, "completed": 1, "failed": 0,
    }
    assert store.queue_summary() == {
        "queued": 3, "running": 1, "completed": 1, "failed": 0,
    }
    positions = {j["id"]: j["queue_position"] for j in store.list_jobs(user_id="u1")}
    assert positions == {mine_queued["id"]: 1, mine_running["id"]: None, mine_done["id"]: None}


def test_batch_store_records_owner(tmp_path):
    store = BatchStore(tmp_path / "jobs.sqlite3")
    owned = store.create_batch(profile="mtb-h37rv", submitted_by_user_id="u1")
    unowned = store.create_batch(profile="mtb-h37rv")
    assert store.get_batch(owned["id"])["submitted_by_user_id"] == "u1"
    assert store.get_batch(unowned["id"])["submitted_by_user_id"] is None
