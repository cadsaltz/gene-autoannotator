from datetime import UTC, datetime, timedelta

import pytest

from backend.access import BOOTSTRAP_ADMIN_EMAIL
from backend.job_store import JobStore
from tests.auth_helpers import make_client, second_client, sign_in, worker_headers

JOB = {"profile": "mtb-h37rv", "locus": "Rv0001"}
USER_ROW_KEYS = {
    "id", "email", "username", "role", "status", "created_at", "last_login_at",
    "quota_max_active", "quota_max_per_day", "quota_max_batch", "active_jobs", "jobs_24h",
    "terms_version", "terms_accepted_at",
}
QUOTA_ENV = (
    "MAX_QUEUED_JOBS", "USER_MAX_ACTIVE_JOBS", "USER_MAX_JOBS_PER_DAY", "USER_MAX_BATCH_SIZE",
    "IP_SIGNUPS_PER_DAY", "IP_SUBMITS_PER_HOUR", "IP_LOGINS_PER_HOUR",
    "OTP_SENDS_PER_EMAIL_PER_HOUR", "APP_VERSION",
)


@pytest.fixture(autouse=True)
def isolate_env(tmp_path, monkeypatch):
    monkeypatch.setenv("PROFILES_DIR", str(tmp_path / "profiles"))
    monkeypatch.delenv("MONGO_URI", raising=False)
    monkeypatch.delenv("MONGODB_URI", raising=False)
    for name in QUOTA_ENV:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def store(tmp_path):
    return JobStore(tmp_path / "jobs.sqlite3")


@pytest.fixture
def alice(tmp_path, store):
    return sign_in(make_client(tmp_path, job_store=store), email="alice@example.com")


@pytest.fixture
def admin(alice):
    return second_client(alice, email=BOOTSTRAP_ADMIN_EMAIL)


def _id(client, email):
    return client.auth_store.get_user_by_email(email)["id"]


def _events(admin, **params):
    response = admin.get("/admin/audit", params=params)
    assert response.status_code == 200
    return response.json()["events"]


def _row(admin, email):
    users = admin.get("/admin/users").json()["users"]
    return next(u for u in users if u["email"] == email)


def test_user_forbidden_on_every_admin_route(alice):
    alice_id = _id(alice, "alice@example.com")
    responses = [
        alice.get("/admin/users"),
        alice.patch(f"/admin/users/{alice_id}", json={"role": "admin"}),
        alice.post(f"/admin/users/{alice_id}/revoke-sessions"),
        alice.delete(f"/admin/users/{alice_id}"),
        alice.get("/admin/overview"),
        alice.get("/admin/audit"),
    ]
    assert [r.status_code for r in responses] == [403] * len(responses)
    assert alice.auth_store.get_user(alice_id)["role"] == "user"


def test_anonymous_gets_401(tmp_path):
    client = make_client(tmp_path)
    assert client.get("/admin/users").status_code == 401
    assert client.get("/admin/overview").status_code == 401


def test_admin_lists_users_with_job_counts(alice, admin, store):
    for _ in range(3):
        assert alice.post("/jobs", json=JOB).status_code == 201
    store.claim_next_queued_job()
    running_then_done = store.claim_next_queued_job()
    store.mark_completed(running_then_done["id"], {})

    response = admin.get("/admin/users")
    assert response.status_code == 200
    users = response.json()["users"]
    assert {u["email"] for u in users} == {"alice@example.com", BOOTSTRAP_ADMIN_EMAIL}
    assert all(set(u) == USER_ROW_KEYS for u in users)
    row = _row(admin, "alice@example.com")
    assert row["role"] == "user"
    assert row["status"] == "active"
    assert row["active_jobs"] == 2
    assert row["jobs_24h"] == 3
    assert row["last_login_at"] is not None
    assert _row(admin, BOOTSTRAP_ADMIN_EMAIL)["active_jobs"] == 0


def test_jobs_24h_excludes_older_jobs(alice, admin, store):
    alice.post("/jobs", json=JOB)
    old = alice.post("/jobs", json=JOB).json()["job_id"]
    stale = (datetime.now(UTC) - timedelta(hours=25)).isoformat()
    with store._connect() as connection:
        connection.execute("UPDATE annotation_jobs SET created_at = ? WHERE id = ?", (stale, old))
    row = _row(admin, "alice@example.com")
    assert row["jobs_24h"] == 1
    assert row["active_jobs"] == 2


def test_list_users_query_filters(alice, admin):
    users = admin.get("/admin/users", params={"query": "alice"}).json()["users"]
    assert [u["email"] for u in users] == ["alice@example.com"]


def test_promoted_user_can_reach_overview(alice, admin):
    alice_id = _id(alice, "alice@example.com")
    assert alice.get("/admin/overview").status_code == 403
    response = admin.patch(f"/admin/users/{alice_id}", json={"role": "admin"})
    assert response.status_code == 200
    assert response.json()["role"] == "admin"
    assert set(response.json()) == USER_ROW_KEYS
    assert alice.get("/admin/overview").status_code == 200

    events = _events(admin, action="role_change")
    assert len(events) == 1
    assert events[0]["target_type"] == "user"
    assert events[0]["target_id"] == alice_id
    assert events[0]["actor_user_id"] == _id(admin, BOOTSTRAP_ADMIN_EMAIL)
    assert events[0]["details"] == {"from": "user", "to": "admin"}


def test_role_change_keeps_sessions(alice, admin):
    alice_id = _id(alice, "alice@example.com")
    admin.patch(f"/admin/users/{alice_id}", json={"role": "admin"})
    admin.patch(f"/admin/users/{alice_id}", json={"role": "user"})
    assert alice.get("/auth/me").status_code == 200
    assert alice.get("/admin/overview").status_code == 403
    assert _events(admin, action="sessions_revoked") == []


def test_suspend_revokes_sessions_and_reactivate_allows_sign_in(alice, admin):
    alice_id = _id(alice, "alice@example.com")
    response = admin.patch(f"/admin/users/{alice_id}", json={"status": "suspended"})
    assert response.status_code == 200
    assert response.json()["status"] == "suspended"
    assert alice.get("/auth/me").status_code in (401, 403)

    status_events = _events(admin, action="status_change")
    assert [e["details"] for e in status_events] == [
        {"from": "active", "to": "suspended", "cancelled_jobs": 0}
    ]
    revoked = _events(admin, action="sessions_revoked")
    assert [e["target_id"] for e in revoked] == [alice_id]
    assert revoked[0]["details"] == {"count": 1}

    assert admin.patch(f"/admin/users/{alice_id}", json={"status": "active"}).status_code == 200
    sign_in(alice, email="alice@example.com")
    assert alice.get("/auth/me").status_code == 200
    assert _events(admin, action="status_change")[0]["details"] == {
        "from": "suspended", "to": "active"
    }


def test_suspend_cancels_queued_and_running_jobs(alice, admin, store):
    alice_id = _id(alice, "alice@example.com")
    job_ids = [alice.post("/jobs", json=JOB).json()["job_id"] for _ in range(4)]
    done = store.claim_next_queued_job()
    store.mark_completed(done["id"], {})
    running = store.claim_next_queued_job()
    admin_job = admin.post("/jobs", json=JOB).json()["job_id"]

    response = admin.patch(f"/admin/users/{alice_id}", json={"status": "suspended"})

    assert response.status_code == 200
    assert response.json()["active_jobs"] == 0
    statuses = {job_id: store.get_job(job_id)["status"] for job_id in job_ids}
    assert statuses == {
        done["id"]: "completed",
        running["id"]: "cancelled",
        job_ids[2]: "cancelled",
        job_ids[3]: "cancelled",
    }
    assert store.get_job(running["id"])["error"] == "Cancelled by admin"
    assert store.get_job(admin_job)["status"] == "queued"
    [event] = _events(admin, action="status_change")
    assert event["details"] == {"from": "active", "to": "suspended", "cancelled_jobs": 3}
    progress = admin.patch(
        f"/jobs/{running['id']}/progress", headers=worker_headers(), json={"current_step": "x"}
    )
    assert progress.status_code == 409


def test_cancel_active_for_user_store(store):
    queued = store.create_job({}, submitted_by_user_id="u1")
    running = store.create_job({}, submitted_by_user_id="u1")
    other = store.create_job({}, submitted_by_user_id="u2")
    store.mark_running(running["id"])
    done = store.create_job({}, submitted_by_user_id="u1")
    store.mark_completed(done["id"], {})

    assert store.cancel_active_for_user("u1", by="cli") == 2

    assert store.get_job(queued["id"])["status"] == "cancelled"
    assert store.get_job(running["id"])["status"] == "cancelled"
    assert store.get_job(running["id"])["error"] == "Cancelled by cli"
    assert store.get_job(running["id"])["lease_expires_at"] is None
    assert store.get_job(done["id"])["status"] == "completed"
    assert store.get_job(other["id"])["status"] == "queued"
    assert store.cancel_active_for_user("u1") == 0


def test_admin_job_list_shows_submitter_email(alice, admin):
    alice_job = alice.post("/jobs", json=JOB).json()["job_id"]
    admin_job = admin.post("/jobs", json=JOB).json()["job_id"]

    listed = {job["id"]: job for job in admin.get("/jobs").json()["jobs"]}
    assert listed[alice_job]["submitted_by_email"] == "alice@example.com"
    assert listed[admin_job]["submitted_by_email"] == BOOTSTRAP_ADMIN_EMAIL
    assert admin.get(f"/jobs/{alice_job}").json()["submitted_by_email"] == "alice@example.com"

    for job in [alice.get(f"/jobs/{alice_job}").json(), *alice.get("/jobs").json()["jobs"]]:
        assert "submitted_by_email" not in job


def test_quota_overrides_round_trip(alice, admin):
    alice_id = _id(alice, "alice@example.com")
    response = admin.patch(
        f"/admin/users/{alice_id}",
        json={"quota_max_active": 3, "quota_max_per_day": 0, "quota_max_batch": 7},
    )
    assert response.status_code == 200
    row = _row(admin, "alice@example.com")
    assert (row["quota_max_active"], row["quota_max_per_day"], row["quota_max_batch"]) == (3, 0, 7)

    assert admin.patch(f"/admin/users/{alice_id}", json={"quota_max_batch": None}).status_code == 200
    row = _row(admin, "alice@example.com")
    assert (row["quota_max_active"], row["quota_max_per_day"], row["quota_max_batch"]) == (3, 0, None)

    events = _events(admin, action="quota_change")
    assert events[0]["details"] == {"quota_max_batch": {"from": 7, "to": None}}
    assert events[1]["details"] == {
        "quota_max_active": {"from": None, "to": 3},
        "quota_max_per_day": {"from": None, "to": 0},
        "quota_max_batch": {"from": None, "to": 7},
    }


def test_quota_override_applies_to_queue_status(alice, admin):
    alice_id = _id(alice, "alice@example.com")
    admin.patch(f"/admin/users/{alice_id}", json={"quota_max_active": 4})
    assert alice.get("/jobs/queue-status").json()["your_active_limit"] == 4


def test_empty_patch_changes_nothing(alice, admin):
    alice_id = _id(alice, "alice@example.com")
    before = _row(admin, "alice@example.com")
    response = admin.patch(f"/admin/users/{alice_id}", json={})
    assert response.status_code == 200
    assert response.json() == before
    actions = {e["action"] for e in _events(admin, user_id=alice_id)}
    assert not actions & {"role_change", "status_change", "quota_change"}


@pytest.mark.parametrize(
    "body",
    [
        {"role": "owner"},
        {"role": None},
        {"status": "pending"},
        {"status": None},
        {"quota_max_active": -1},
        {"quota_max_per_day": "5"},
        {"quota_max_batch": 2.5},
        {"quota_max_batch": True},
        {"unknown_field": 1},
    ],
)
def test_patch_rejects_invalid_values(alice, admin, body):
    alice_id = _id(alice, "alice@example.com")
    before = _row(admin, "alice@example.com")
    assert admin.patch(f"/admin/users/{alice_id}", json=body).status_code == 422
    assert _row(admin, "alice@example.com") == before


def test_oversized_quota_rejects_whole_patch(alice, admin):
    alice_id = _id(alice, "alice@example.com")
    before = _row(admin, "alice@example.com")
    response = admin.patch(
        f"/admin/users/{alice_id}", json={"role": "admin", "quota_max_active": 2**31}
    )
    assert response.status_code == 422
    assert _row(admin, "alice@example.com") == before
    ok = admin.patch(f"/admin/users/{alice_id}", json={"quota_max_active": 2**31 - 1})
    assert ok.status_code == 200


def test_combined_demote_and_suspend_blocked_for_last_admin(admin):
    admin_id = _id(admin, BOOTSTRAP_ADMIN_EMAIL)
    response = admin.patch(
        f"/admin/users/{admin_id}", json={"role": "user", "status": "suspended"}
    )
    assert response.status_code == 409
    user = admin.auth_store.get_user(admin_id)
    assert (user["role"], user["status"]) == ("admin", "active")
    assert admin.get("/auth/me").status_code == 200
    assert _events(admin, action="role_change") == []
    assert _events(admin, action="status_change") == []


def test_combined_demote_and_suspend_for_non_last_admin(alice, admin):
    alice_id = _id(alice, "alice@example.com")
    admin.patch(f"/admin/users/{alice_id}", json={"role": "admin"})
    response = admin.patch(
        f"/admin/users/{alice_id}", json={"role": "user", "status": "suspended"}
    )
    assert response.status_code == 200
    assert (response.json()["role"], response.json()["status"]) == ("user", "suspended")
    assert alice.get("/auth/me").status_code in (401, 403)
    revoked = _events(admin, action="sessions_revoked")
    assert [(e["target_id"], e["details"]) for e in revoked] == [(alice_id, {"count": 1})]


def test_unknown_user_returns_404(admin):
    assert admin.patch("/admin/users/nope", json={"role": "admin"}).status_code == 404
    assert admin.post("/admin/users/nope/revoke-sessions").status_code == 404
    assert admin.delete("/admin/users/nope").status_code == 404


@pytest.mark.parametrize(
    "action",
    [
        lambda admin, admin_id: admin.patch(f"/admin/users/{admin_id}", json={"role": "user"}),
        lambda admin, admin_id: admin.patch(f"/admin/users/{admin_id}", json={"status": "suspended"}),
        lambda admin, admin_id: admin.delete(f"/admin/users/{admin_id}"),
    ],
    ids=["demote", "suspend", "delete"],
)
def test_last_admin_guard(admin, action):
    admin_id = _id(admin, BOOTSTRAP_ADMIN_EMAIL)
    response = action(admin, admin_id)
    assert response.status_code == 409
    assert response.json() == {"detail": "Cannot remove the last admin"}
    user = admin.auth_store.get_user(admin_id)
    assert (user["role"], user["status"]) == ("admin", "active")
    assert admin.get("/auth/me").status_code == 200


def test_last_admin_guard_blocks_combined_patch_atomically(admin):
    admin_id = _id(admin, BOOTSTRAP_ADMIN_EMAIL)
    response = admin.patch(
        f"/admin/users/{admin_id}", json={"quota_max_active": 1, "role": "user"}
    )
    assert response.status_code == 409
    assert admin.auth_store.get_user(admin_id)["quota_max_active"] is None


def test_suspended_admin_does_not_count_toward_guard(alice, admin):
    alice_id = _id(alice, "alice@example.com")
    admin_id = _id(admin, BOOTSTRAP_ADMIN_EMAIL)
    admin.patch(f"/admin/users/{alice_id}", json={"role": "admin"})
    admin.patch(f"/admin/users/{alice_id}", json={"status": "suspended"})
    response = admin.patch(f"/admin/users/{admin_id}", json={"role": "user"})
    assert response.status_code == 409


def test_admin_can_demote_self_when_another_admin_exists(alice, admin):
    alice_id = _id(alice, "alice@example.com")
    admin_id = _id(admin, BOOTSTRAP_ADMIN_EMAIL)
    admin.patch(f"/admin/users/{alice_id}", json={"role": "admin"})
    assert admin.patch(f"/admin/users/{admin_id}", json={"role": "user"}).status_code == 200
    assert admin.get("/admin/overview").status_code == 403
    assert alice.patch(f"/admin/users/{alice_id}", json={"role": "user"}).status_code == 409


def test_revoke_sessions(alice, admin):
    alice_id = _id(alice, "alice@example.com")
    response = admin.post(f"/admin/users/{alice_id}/revoke-sessions")
    assert response.status_code == 200
    assert response.json() == {"revoked": 1}
    assert alice.get("/auth/me").status_code == 401
    assert admin.auth_store.get_user(alice_id)["status"] == "active"
    events = _events(admin, action="sessions_revoked")
    assert [(e["target_id"], e["details"]) for e in events] == [(alice_id, {"count": 1})]


def test_delete_user_cancels_active_jobs(alice, admin, store):
    alice_id = _id(alice, "alice@example.com")
    job_ids = [alice.post("/jobs", json=JOB).json()["job_id"] for _ in range(3)]
    running = store.claim_next_queued_job()
    assert running["id"] == job_ids[0]

    response = admin.delete(f"/admin/users/{alice_id}")
    assert response.status_code == 200
    assert response.json() == {"deleted": True, "cancelled_jobs": 3}

    assert admin.auth_store.get_user(alice_id) is None
    assert alice.get("/auth/me").status_code == 401
    jobs = [store.get_job(job_id) for job_id in job_ids]
    assert [j["status"] for j in jobs] == ["cancelled"] * 3
    assert all(j["submitted_by_user_id"] is None for j in jobs)
    assert all(u["email"] != "alice@example.com" for u in admin.get("/admin/users").json()["users"])

    events = _events(admin, action="user_delete")
    assert len(events) == 1
    assert events[0]["target_type"] == "user"
    assert events[0]["target_id"] == alice_id
    assert events[0]["details"]["email"] == "a***@example.com"
    assert events[0]["details"]["cancelled_jobs"] == 3
    assert events[0]["details"]["anonymized_jobs"] == 3


def test_delete_audited_even_if_cancel_fails(alice, admin, store, monkeypatch):
    alice_id = _id(alice, "alice@example.com")

    def boom(user_id, **kwargs):
        raise RuntimeError("database is locked")

    monkeypatch.setattr(store, "cancel_active_for_user", boom)
    with pytest.raises(RuntimeError):
        admin.delete(f"/admin/users/{alice_id}")
    assert admin.auth_store.get_user(alice_id) is None
    events = _events(admin, action="user_delete")
    assert len(events) == 1
    assert events[0]["target_id"] == alice_id
    assert events[0]["details"]["email"] == "a***@example.com"
    assert events[0]["details"]["cancelled_jobs"] is None
    assert events[0]["details"]["anonymized_jobs"] is None


def test_counts_since_store(store):
    done = store.create_job({})
    failed = store.create_job({})
    store.create_job({})
    store.mark_completed(done["id"], {})
    store.mark_failed(failed["id"], "boom")
    since = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    counts = store.counts_since(since)
    assert counts["completed"] == 1
    assert counts["failed"] == 1
    future = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    assert store.counts_since(future)["completed"] == 0


def test_overview(alice, admin, store, monkeypatch):
    monkeypatch.setenv("USER_MAX_ACTIVE_JOBS", "9")
    monkeypatch.setenv("IP_SUBMITS_PER_HOUR", "11")
    monkeypatch.setenv("APP_VERSION", "1.2.3")
    for _ in range(4):
        assert alice.post("/jobs", json=JOB).status_code == 201
    store.claim_next_queued_job()
    done = store.claim_next_queued_job()
    store.mark_completed(done["id"], {})
    failed = store.claim_next_queued_job()
    store.mark_failed(failed["id"], "boom")
    admin.post("/workers/register", headers=worker_headers(), json={
        "worker_name": "w1", "hostname": "w1", "agent_version": "0.1.0",
        "total_memory_bytes": 1, "dedicated_memory_bytes": 1, "max_slots": 1,
        "ollama_models": [],
    })
    # Set directly: suspending through the API would also cancel alice's jobs.
    admin.auth_store.set_status(_id(alice, "alice@example.com"), "suspended")

    response = admin.get("/admin/overview")
    assert response.status_code == 200
    body = response.json()
    assert {
        "queued", "running", "failed_24h", "completed_24h", "workers_online",
        "users_total", "users_suspended", "quota_config",
    } <= set(body)
    assert (body["queued"], body["running"]) == (1, 1)
    assert (body["completed_24h"], body["failed_24h"]) == (1, 1)
    assert body["workers_online"] == 1
    assert (body["users_total"], body["users_suspended"]) == (2, 1)
    assert body["version"] == "1.2.3"
    assert body["quota_config"] == {
        "max_queued": 200,
        "user_max_active": 9,
        "user_max_per_day": 50,
        "user_max_batch": 25,
        "ip_signups_per_day": 5,
        "ip_submits_per_hour": 11,
        "ip_logins_per_hour": 30,
        "otp_sends_per_email_per_hour": 5,
    }


def _suspend_during_quota_check(monkeypatch, client, user_id):
    from backend import api

    real_check = api.check_submission

    def check_then_suspend(**kwargs):
        real_check(**kwargs)
        client.auth_store.set_status(user_id, "suspended")

    monkeypatch.setattr(api, "check_submission", check_then_suspend)


@pytest.mark.parametrize(
    "path, body",
    [
        ("/jobs", JOB),
        (
            "/batches",
            {
                "profile": "mtb-h37rv",
                "entries": [{"input": "Rv0001"}, {"input": "Rv0002"}],
                "allow_online_name_lookup": False,
            },
        ),
    ],
)
def test_submission_rejected_when_suspended_mid_request(alice, store, monkeypatch, path, body):
    _suspend_during_quota_check(monkeypatch, alice, _id(alice, "alice@example.com"))

    response = alice.post(path, json=body)

    assert response.status_code == 403
    assert response.json() == {"detail": "Account suspended"}
    assert store.count_queued_jobs() == 0


def test_suspend_and_delete_hold_submission_lock(alice, admin, store, monkeypatch):
    alice_id = _id(alice, "alice@example.com")
    lock = admin.app.state.submission_lock
    held = []

    def spy(method_name):
        real = getattr(store, method_name)

        def wrapper(user_id, **kwargs):
            held.append((method_name, lock.locked()))
            return real(user_id, **kwargs)

        monkeypatch.setattr(store, method_name, wrapper)

    spy("cancel_active_for_user")
    spy("anonymize_user")
    admin.patch(f"/admin/users/{alice_id}", json={"status": "suspended"})
    admin.delete(f"/admin/users/{alice_id}")
    assert held == [
        ("cancel_active_for_user", True),
        ("cancel_active_for_user", True),
        ("anonymize_user", True),
    ]


def test_status_change_audited_even_if_cancel_fails(alice, admin, store, monkeypatch):
    alice_id = _id(alice, "alice@example.com")

    def boom(user_id, **kwargs):
        raise RuntimeError("database is locked")

    monkeypatch.setattr(store, "cancel_active_for_user", boom)
    with pytest.raises(RuntimeError):
        admin.patch(f"/admin/users/{alice_id}", json={"status": "suspended"})
    [event] = _events(admin, action="status_change")
    assert event["details"] == {"from": "active", "to": "suspended", "cancelled_jobs": None}


def test_claim_skips_and_cancels_suspended_users_jobs(alice, admin, store):
    alice_id = _id(alice, "alice@example.com")
    alice_job = alice.post("/jobs", json=JOB).json()["job_id"]
    admin_job = admin.post("/jobs", json=JOB).json()["job_id"]
    legacy = store.create_job({})
    unknown_owner = store.create_job({}, submitted_by_user_id="deleted-or-unknown")
    alice.auth_store.set_status(alice_id, "suspended")

    claimed = [store.assign_job_to_worker("w1")["id"] for _ in range(3)]

    assert claimed == [admin_job, legacy["id"], unknown_owner["id"]]
    assert store.assign_job_to_worker("w1") is None
    skipped = store.get_job(alice_job)
    assert skipped["status"] == "cancelled"
    assert skipped["error"] == "Cancelled: account suspended"


def test_claim_works_without_users_table(tmp_path):
    from backend.job_store import JobStore

    bare = JobStore(tmp_path / "bare.sqlite3")
    job = bare.create_job({}, submitted_by_user_id="u1")
    assert bare.assign_job_to_worker("w1")["id"] == job["id"]
