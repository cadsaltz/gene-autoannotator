import logging

import pytest

from backend.access import BOOTSTRAP_ADMIN_EMAIL
from backend.api import MAX_BATCH_SIZE
from backend.quotas import QuotaConfig, effective_limits
from tests.auth_helpers import make_client, second_client, sign_in, signed_in_client

JOB = {"profile": "mtb-h37rv", "locus": "Rv0001"}
QUOTA_ENV = (
    "MAX_QUEUED_JOBS",
    "USER_MAX_ACTIVE_JOBS",
    "USER_MAX_JOBS_PER_DAY",
    "USER_MAX_BATCH_SIZE",
    "SUBMISSIONS_PAUSED",
)
PAUSED_BODY = {"detail": "New submissions are paused. Please try again later.", "code": "paused"}


def _batch(count: int) -> dict:
    return {
        "profile": "mtb-h37rv",
        "entries": [{"input": f"Rv{index:04d}"} for index in range(1, count + 1)],
        "allow_online_name_lookup": False,
    }


@pytest.fixture(autouse=True)
def isolate_env(tmp_path, monkeypatch):
    monkeypatch.setenv("PROFILES_DIR", str(tmp_path / "profiles"))
    monkeypatch.delenv("MONGO_URI", raising=False)
    monkeypatch.delenv("MONGODB_URI", raising=False)
    for name in QUOTA_ENV:
        monkeypatch.delenv(name, raising=False)


def test_quota_config_defaults_and_bad_values(monkeypatch):
    assert QuotaConfig.from_env() == QuotaConfig(
        max_queued=200, user_max_active=20, user_max_per_day=50, user_max_batch=25
    )
    monkeypatch.setenv("MAX_QUEUED_JOBS", "not-a-number")
    monkeypatch.setenv("USER_MAX_ACTIVE_JOBS", "3")
    config = QuotaConfig.from_env()
    assert config.max_queued == 200
    assert config.user_max_active == 3


def test_unparseable_quota_env_logs_warning(monkeypatch, caplog):
    monkeypatch.setenv("USER_MAX_JOBS_PER_DAY", "lots")
    with caplog.at_level(logging.WARNING, logger="backend.quotas"):
        assert QuotaConfig.from_env().user_max_per_day == 50
    assert any("USER_MAX_JOBS_PER_DAY" in record.getMessage() for record in caplog.records)


def test_zero_or_negative_limits_mean_unlimited():
    config = QuotaConfig(max_queued=0, user_max_active=0, user_max_per_day=-1, user_max_batch=0)
    user = {"role": "user", "status": "active", "quota_max_active": None,
            "quota_max_per_day": None, "quota_max_batch": None}
    assert effective_limits(user, config) == {
        "max_active": None, "max_per_day": None, "max_batch": None,
    }
    capped = QuotaConfig(max_queued=0, user_max_active=1, user_max_per_day=1, user_max_batch=1)
    overridden = {**user, "quota_max_active": 0, "quota_max_per_day": -5, "quota_max_batch": 0}
    assert effective_limits(overridden, capped) == {
        "max_active": None, "max_per_day": None, "max_batch": None,
    }


def test_zero_user_batch_size_is_unlimited(tmp_path, monkeypatch):
    monkeypatch.setenv("USER_MAX_BATCH_SIZE", "0")
    alice = signed_in_client(tmp_path, email="alice@example.com")
    assert alice.post("/jobs", json=JOB).status_code == 201
    assert alice.post("/batches", json=_batch(3)).status_code == 201
    assert alice.get("/jobs/queue-status").json()["batch_limit"] == MAX_BATCH_SIZE


def test_zero_per_user_override_is_unlimited(tmp_path, monkeypatch):
    monkeypatch.setenv("USER_MAX_ACTIVE_JOBS", "1")
    alice, store = signed_in_client(tmp_path, email="alice@example.com", return_store=True)
    user = store.get_user_by_email("alice@example.com")
    store.set_quota_overrides(user["id"], max_active=0, max_per_day=None, max_batch=None)
    for _ in range(3):
        assert alice.post("/jobs", json=JOB).status_code == 201
    assert alice.get("/jobs/queue-status").json()["your_active_limit"] is None


def test_batch_that_overflows_global_queue_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("MAX_QUEUED_JOBS", "3")
    alice = signed_in_client(tmp_path, email="alice@example.com")
    assert alice.post("/jobs", json=JOB).status_code == 201
    resp = alice.post("/batches", json=_batch(3))
    assert resp.status_code == 429
    assert resp.json()["code"] == "queue_full"
    assert alice.get("/jobs/queue-status").json()["queued"] == 1


def test_effective_limits_prefers_overrides_and_frees_admins():
    config = QuotaConfig(max_queued=5, user_max_active=2, user_max_per_day=4, user_max_batch=3)
    user = {"role": "user", "status": "active", "quota_max_active": 7,
            "quota_max_per_day": None, "quota_max_batch": None}
    admin = {"role": "admin", "status": "active"}
    assert effective_limits(user, config) == {"max_active": 7, "max_per_day": 4, "max_batch": 3}
    assert effective_limits(admin, config) == {
        "max_active": None, "max_per_day": None, "max_batch": None,
    }


def test_global_queue_cap_blocks_users(tmp_path, monkeypatch):
    monkeypatch.setenv("MAX_QUEUED_JOBS", "1")
    alice = signed_in_client(tmp_path, email="alice@example.com")
    assert alice.post("/jobs", json=JOB).status_code == 201
    resp = alice.post("/jobs", json=JOB)
    assert resp.status_code == 429
    assert resp.json() == {
        "detail": "The queue is full right now. Please try again later.",
        "code": "queue_full",
    }


def test_global_queue_cap_counts_other_users_jobs(tmp_path, monkeypatch):
    monkeypatch.setenv("MAX_QUEUED_JOBS", "1")
    alice = signed_in_client(tmp_path, email="alice@example.com")
    bob = second_client(alice, email="bob@example.com")
    assert alice.post("/jobs", json=JOB).status_code == 201
    assert bob.post("/jobs", json=JOB).json()["code"] == "queue_full"


def test_zero_queue_cap_means_unlimited(tmp_path, monkeypatch):
    monkeypatch.setenv("MAX_QUEUED_JOBS", "0")
    alice = signed_in_client(tmp_path, email="alice@example.com")
    for _ in range(3):
        assert alice.post("/jobs", json=JOB).status_code == 201
    assert alice.get("/jobs/queue-status").json()["accepting"] is True


def test_admin_bypasses_queue_cap(tmp_path, monkeypatch):
    monkeypatch.setenv("MAX_QUEUED_JOBS", "1")
    admin = signed_in_client(tmp_path, email=BOOTSTRAP_ADMIN_EMAIL)
    assert admin.post("/jobs", json=JOB).status_code == 201
    assert admin.post("/jobs", json=JOB).status_code == 201


def test_user_active_limit(tmp_path, monkeypatch):
    monkeypatch.setenv("USER_MAX_ACTIVE_JOBS", "1")
    alice = signed_in_client(tmp_path, email="alice@example.com")
    assert alice.post("/jobs", json=JOB).status_code == 201
    resp = alice.post("/jobs", json=JOB)
    assert resp.status_code == 429
    assert resp.json()["code"] == "active_limit"


def test_user_daily_limit(tmp_path, monkeypatch):
    monkeypatch.setenv("USER_MAX_JOBS_PER_DAY", "1")
    monkeypatch.setenv("USER_MAX_ACTIVE_JOBS", "10")
    alice = signed_in_client(tmp_path, email="alice@example.com")
    assert alice.post("/jobs", json=JOB).status_code == 201
    resp = alice.post("/jobs", json=JOB)
    assert resp.status_code == 429
    assert resp.json()["code"] == "daily_limit"


def test_per_user_override_beats_env(tmp_path, monkeypatch):
    monkeypatch.setenv("USER_MAX_ACTIVE_JOBS", "1")
    alice, store = signed_in_client(tmp_path, email="alice@example.com", return_store=True)
    user = store.get_user_by_email("alice@example.com")
    store.set_quota_overrides(user["id"], max_active=5, max_per_day=None, max_batch=None)
    assert alice.post("/jobs", json=JOB).status_code == 201
    assert alice.post("/jobs", json=JOB).status_code == 201


def test_batch_size_limit_for_users(tmp_path, monkeypatch):
    monkeypatch.setenv("USER_MAX_BATCH_SIZE", "2")
    alice = signed_in_client(tmp_path, email="alice@example.com")
    resp = alice.post("/batches", json=_batch(3))
    assert resp.status_code == 429
    assert resp.json()["code"] == "batch_limit"
    assert alice.get("/jobs/queue-status").json()["your_today"] == 0


def test_batch_counts_every_job_against_active_limit(tmp_path, monkeypatch):
    monkeypatch.setenv("USER_MAX_ACTIVE_JOBS", "2")
    alice = signed_in_client(tmp_path, email="alice@example.com")
    assert alice.post("/jobs", json=JOB).status_code == 201
    resp = alice.post("/batches", json=_batch(2))
    assert resp.status_code == 429
    assert resp.json()["code"] == "active_limit"


def test_admin_bypasses_user_batch_limit(tmp_path, monkeypatch):
    monkeypatch.setenv("USER_MAX_BATCH_SIZE", "1")
    admin = signed_in_client(tmp_path, email=BOOTSTRAP_ADMIN_EMAIL)
    assert admin.post("/batches", json=_batch(2)).status_code == 201


def test_batch_validate_does_not_consume_quota(tmp_path, monkeypatch):
    monkeypatch.setenv("USER_MAX_JOBS_PER_DAY", "2")
    alice = signed_in_client(tmp_path, email="alice@example.com")
    for _ in range(3):
        assert alice.post("/batches/validate", json=_batch(2)).status_code == 200
    assert alice.post("/batches", json=_batch(2)).status_code == 201


def test_batch_validate_warns_about_batch_limit(tmp_path, monkeypatch):
    monkeypatch.setenv("USER_MAX_BATCH_SIZE", "1")
    alice = signed_in_client(tmp_path, email="alice@example.com")
    resp = alice.post("/batches/validate", json=_batch(2))
    assert resp.status_code == 429
    assert resp.json()["code"] == "batch_limit"


def test_queue_status_reports_user_limits(tmp_path, monkeypatch):
    monkeypatch.setenv("MAX_QUEUED_JOBS", "2")
    monkeypatch.setenv("USER_MAX_ACTIVE_JOBS", "4")
    monkeypatch.setenv("USER_MAX_JOBS_PER_DAY", "9")
    monkeypatch.setenv("USER_MAX_BATCH_SIZE", "3")
    alice = signed_in_client(tmp_path, email="alice@example.com")
    alice.post("/jobs", json=JOB)
    assert alice.get("/jobs/queue-status").json() == {
        "queued": 1,
        "accepting": True,
        "paused": False,
        "your_active": 1,
        "your_active_limit": 4,
        "your_today": 1,
        "your_daily_limit": 9,
        "batch_limit": 3,
    }
    alice.post("/jobs", json=JOB)
    assert alice.get("/jobs/queue-status").json()["accepting"] is False


def test_queue_status_batch_limit_never_exceeds_absolute_cap(tmp_path, monkeypatch):
    monkeypatch.setenv("USER_MAX_BATCH_SIZE", str(MAX_BATCH_SIZE + 100))
    alice = signed_in_client(tmp_path, email="alice@example.com")
    assert alice.get("/jobs/queue-status").json()["batch_limit"] == MAX_BATCH_SIZE


def test_queue_status_for_admin_is_unlimited(tmp_path, monkeypatch):
    monkeypatch.setenv("MAX_QUEUED_JOBS", "1")
    admin = signed_in_client(tmp_path, email=BOOTSTRAP_ADMIN_EMAIL)
    admin.post("/jobs", json=JOB)
    body = admin.get("/jobs/queue-status").json()
    assert body["your_active_limit"] is None
    assert body["your_daily_limit"] is None
    assert body["batch_limit"] == MAX_BATCH_SIZE
    assert body["accepting"] is True


def _no_worker_clients(tmp_path):
    user = sign_in(make_client(tmp_path, worker_capacity_required=True), email="alice@example.com")
    admin = second_client(user, BOOTSTRAP_ADMIN_EMAIL)
    return user, admin


def test_user_submit_without_workers_hides_fleet_state(tmp_path):
    user, _admin = _no_worker_clients(tmp_path)
    for response in (user.post("/jobs", json=JOB), user.post("/batches", json=_batch(2))):
        assert response.status_code == 503
        body = response.json()
        assert body["code"] == "unavailable"
        assert "worker" not in body["detail"].lower()
        assert "try again later" in body["detail"].lower()


def test_admin_submit_without_workers_keeps_detailed_reason(tmp_path):
    _user, admin = _no_worker_clients(tmp_path)
    for response in (admin.post("/jobs", json=JOB), admin.post("/batches", json=_batch(2))):
        assert response.status_code == 503
        assert response.json()["detail"] == "No workers connected with job capacity."


def test_paused_submissions_reject_users(tmp_path, monkeypatch):
    alice = signed_in_client(tmp_path, email="alice@example.com")
    assert alice.get("/jobs/queue-status").json()["paused"] is False
    monkeypatch.setenv("SUBMISSIONS_PAUSED", "1")

    for response in (alice.post("/jobs", json=JOB), alice.post("/batches", json=_batch(2))):
        assert response.status_code == 503
        assert response.json() == PAUSED_BODY
    status = alice.get("/jobs/queue-status").json()
    assert (status["accepting"], status["paused"], status["queued"]) == (False, True, 0)

    monkeypatch.setenv("SUBMISSIONS_PAUSED", "0")
    assert alice.post("/jobs", json=JOB).status_code == 201
    assert alice.get("/jobs/queue-status").json()["accepting"] is True


def test_paused_takes_precedence_over_missing_workers(tmp_path, monkeypatch):
    monkeypatch.setenv("SUBMISSIONS_PAUSED", "1")
    user, _admin = _no_worker_clients(tmp_path)
    assert user.post("/jobs", json=JOB).json() == PAUSED_BODY


def test_admin_bypasses_paused_submissions(tmp_path, monkeypatch):
    monkeypatch.setenv("SUBMISSIONS_PAUSED", "1")
    admin = signed_in_client(tmp_path, email=BOOTSTRAP_ADMIN_EMAIL)
    assert admin.post("/jobs", json=JOB).status_code == 201
    assert admin.post("/batches", json=_batch(2)).status_code == 201
    status = admin.get("/jobs/queue-status").json()
    assert (status["accepting"], status["paused"]) == (True, True)
