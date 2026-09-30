import sqlite3
import time
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from backend import backup
from backend.access import BOOTSTRAP_ADMIN_EMAIL
from backend.audit_store import AuditStore, mask_email
from backend.auth_store import AuthStore
from backend.batch_store import BatchStore
from backend.job_store import JobStore
from backend.rate_limits import RateLimiter
from tests.auth_helpers import make_client, second_client, sign_in, worker_headers

JOB = {"profile": "mtb-h37rv", "locus": "Rv0001"}
BATCH = {
    "profile": "mtb-h37rv",
    "entries": [{"input": "Rv0001"}, {"input": "Rv0002"}],
    "allow_online_name_lookup": False,
}
NOW = datetime(2026, 6, 1, tzinfo=UTC)


@pytest.fixture(autouse=True)
def isolate_env(tmp_path, monkeypatch):
    monkeypatch.setenv("PROFILES_DIR", str(tmp_path / "profiles"))
    for name in (
        "MONGO_URI", "MONGODB_URI", "JOB_RETENTION_DAYS", "AUDIT_RETENTION_DAYS",
        "IP_SIGNUPS_PER_DAY", "IP_LOGINS_PER_HOUR", "OTP_SENDS_PER_EMAIL_PER_HOUR",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "jobs.sqlite3"


@pytest.fixture
def store(db_path):
    return JobStore(db_path)


@pytest.fixture
def alice(tmp_path, store):
    return sign_in(make_client(tmp_path, job_store=store), email="alice@example.com")


@pytest.fixture
def admin(alice):
    return second_client(alice, email=BOOTSTRAP_ADMIN_EMAIL)


def _id(client, email):
    return client.auth_store.get_user_by_email(email)["id"]


def _rows(db_path, sql, params=()):
    with sqlite3.connect(db_path) as connection:
        return connection.execute(sql, params).fetchall()


def _iso(delta):
    return (NOW + delta).isoformat()


# --- email masking ----------------------------------------------------------


@pytest.mark.parametrize(
    ("email", "masked"),
    [
        ("sam@gmail.com", "s***@gmail.com"),
        ("Sam.Smith+x@Example.org", "s***@example.org"),
        ("a@b.co", "a***@b.co"),
        ("not-an-email", "***"),
        ("", "***"),
    ],
)
def test_mask_email(email, masked):
    assert mask_email(email) == masked


def test_audit_store_masks_emails_in_existing_user_delete_events(db_path):
    audit = AuditStore(db_path)
    audit.record(action="user_delete", actor_user_id="admin", target_type="user",
                 target_id="u1", details={"email": "alice@example.com", "cancelled_jobs": 1})
    audit.record(action="user_delete", actor_user_id="admin", target_type="user",
                 target_id="u2", details={"email": "b***@example.com"})
    audit.record(action="status_change", actor_user_id="admin", details={"from": "active"})

    AuditStore(db_path)

    events = {e["target_id"]: e for e in audit.list(action="user_delete")}
    assert events["u1"]["details"] == {"email": "a***@example.com", "cancelled_jobs": 1}
    assert events["u2"]["details"] == {"email": "b***@example.com"}
    assert not _rows(db_path, "SELECT 1 FROM audit_events WHERE details_json LIKE '%alice@%'")


# --- account deletion -------------------------------------------------------


def test_delete_user_cancels_active_jobs_and_anonymizes_rows(alice, admin, store, db_path):
    alice_id = _id(alice, "alice@example.com")
    batch = alice.post("/batches", json=BATCH).json()
    solo = alice.post("/jobs", json=JOB).json()["job_id"]
    running = store.claim_next_queued_job()
    store.mark_running(solo)
    store.mark_completed(solo, {})
    admin_job = admin.post("/jobs", json=JOB).json()["job_id"]

    response = admin.delete(f"/admin/users/{alice_id}")

    assert response.status_code == 200
    assert response.json() == {"deleted": True, "cancelled_jobs": 2}
    alice_jobs = [store.get_job(job_id) for job_id in [*batch["job_ids"], solo]]
    assert sorted(j["status"] for j in alice_jobs) == ["cancelled", "cancelled", "completed"]
    assert running["id"] in batch["job_ids"]
    assert all(j["submitted_by_user_id"] is None for j in alice_jobs)
    assert BatchStore(db_path).get_batch(batch["batch_id"])["submitted_by_user_id"] is None
    assert store.get_job(admin_job)["submitted_by_user_id"] == _id(admin, BOOTSTRAP_ADMIN_EMAIL)
    assert not _rows(db_path, "SELECT 1 FROM annotation_jobs WHERE submitted_by_user_id = ?",
                     (alice_id,))


def test_worker_learns_deleted_users_running_job_was_cancelled(alice, admin, store):
    alice_id = _id(alice, "alice@example.com")
    job_id = alice.post("/jobs", json=JOB).json()["job_id"]
    store.claim_next_queued_job()

    admin.delete(f"/admin/users/{alice_id}")

    response = admin.patch(
        f"/jobs/{job_id}/progress", json={"current_step": "x"}, headers=worker_headers()
    )
    assert response.status_code == 409
    assert response.json()["cancelled"] is True


def test_anonymized_jobs_stay_visible_to_admins_without_submitter(alice, admin):
    alice_id = _id(alice, "alice@example.com")
    job_id = alice.post("/jobs", json=JOB).json()["job_id"]
    batch_id = alice.post("/batches", json=BATCH).json()["batch_id"]

    admin.delete(f"/admin/users/{alice_id}")

    detail = admin.get(f"/jobs/{job_id}")
    assert detail.status_code == 200
    assert detail.json()["submitted_by_user_id"] is None
    assert detail.json()["submitted_by_email"] is None
    listed = admin.get("/jobs").json()["jobs"]
    assert job_id in [j["id"] for j in listed]
    assert admin.get(f"/batches/{batch_id}").status_code == 200
    assert admin.get("/admin/users").status_code == 200
    assert admin.get("/admin/overview").status_code == 200


def test_new_account_with_same_email_does_not_inherit_old_jobs(alice, admin):
    alice_id = _id(alice, "alice@example.com")
    alice.post("/jobs", json=JOB)
    admin.delete(f"/admin/users/{alice_id}")

    again = sign_in(TestClient(alice.app), email="alice@example.com")

    assert again.get("/jobs").json()["jobs"] == []
    assert again.get("/jobs").json()["queue"]["queued"] == 0
    assert again.post("/jobs", json=JOB).status_code == 201


def test_delete_user_removes_codes_and_email_rate_limit_rows(alice, admin, db_path):
    alice_id = _id(alice, "alice@example.com")
    alice.post("/auth/login", json={"email": "alice@example.com"})
    assert _rows(db_path, "SELECT 1 FROM login_codes WHERE email = 'alice@example.com'")
    assert _rows(db_path, "SELECT 1 FROM rate_events WHERE key = 'alice@example.com'")
    other_rows = "SELECT COUNT(*) FROM rate_events WHERE key != 'alice@example.com'"
    other_before = _rows(db_path, other_rows)

    admin.delete(f"/admin/users/{alice_id}")

    assert not _rows(db_path, "SELECT 1 FROM login_codes WHERE email = 'alice@example.com'")
    assert not _rows(db_path, "SELECT 1 FROM sessions WHERE user_id = ?", (alice_id,))
    assert not _rows(db_path, "SELECT 1 FROM rate_events WHERE key = 'alice@example.com'")
    assert _rows(db_path, other_rows) == other_before


def test_user_delete_audit_event_masks_email(alice, admin, db_path):
    alice_id = _id(alice, "alice@example.com")

    admin.delete(f"/admin/users/{alice_id}")

    [event] = admin.get("/admin/audit", params={"action": "user_delete"}).json()["events"]
    assert event["target_id"] == alice_id
    assert event["details"]["email"] == "a***@example.com"
    assert event["details"]["cancelled_jobs"] == 0
    assert event["details"]["anonymized_jobs"] == 0
    assert not _rows(db_path,
                     "SELECT 1 FROM audit_events WHERE details_json LIKE '%alice@example.com%'")


def test_anonymize_store_methods(db_path):
    store = JobStore(db_path)
    batches = BatchStore(db_path)
    batch = batches.create_batch(submitted_by_user_id="u1")
    store.create_job({}, batch_id=batch["id"], submitted_by_user_id="u1")
    store.create_job({}, submitted_by_user_id="u1")
    other = store.create_job({}, submitted_by_user_id="u2")

    assert store.anonymize_user("u1") == {"jobs": 2, "batches": 1}

    assert store.list_jobs(user_id="u1") == []
    assert batches.get_batch(batch["id"])["submitted_by_user_id"] is None
    assert store.get_job(other["id"])["submitted_by_user_id"] == "u2"
    assert store.count_active_for_user("u1") == 0
    assert store.anonymize_user("u1") == {"jobs": 0, "batches": 0}


def test_anonymize_without_batch_table(db_path):
    store = JobStore(db_path)
    store.create_job({}, submitted_by_user_id="u1")
    assert store.anonymize_user("u1") == {"jobs": 1, "batches": 0}


def test_rate_limiter_forget_key(db_path):
    limiter = RateLimiter(db_path)
    limiter.hit("otp_send", "alice@example.com", 3600, 10)
    limiter.hit("otp_send", "bob@example.com", 3600, 10)
    limiter.hit("ip_login", "127.0.0.1", 3600, 10)

    assert limiter.forget_key("alice@example.com") == 1

    assert _rows(db_path, "SELECT key FROM rate_events ORDER BY key") == [
        ("127.0.0.1",), ("bob@example.com",),
    ]


# --- scheduled purges -------------------------------------------------------


def _insert_session(db_path, session_id, expires_at):
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "INSERT INTO sessions (id, user_id, token_hash, expires_at, created_at, last_seen_at)"
            " VALUES (?, 'u1', ?, ?, ?, ?)",
            (session_id, f"hash-{session_id}", expires_at, _iso(-timedelta(days=100)),
             _iso(-timedelta(days=100))),
        )


def _insert_code(db_path, code_id, expires_at, used_at=None):
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "INSERT INTO login_codes (id, email, purpose, code_hash, expires_at, used_at,"
            " attempt_count, created_at) VALUES (?, 'a@example.com', 'login', 'h', ?, ?, 0, ?)",
            (code_id, expires_at, used_at, _iso(-timedelta(days=3))),
        )


def _ids(db_path, table):
    return sorted(row[0] for row in _rows(db_path, f"SELECT id FROM {table}"))


def test_auth_store_purges_expired_sessions_and_old_codes(db_path):
    auth = AuthStore(db_path)
    _insert_session(db_path, "old", _iso(-timedelta(days=2)))
    _insert_session(db_path, "just-expired", _iso(-timedelta(hours=1)))
    _insert_session(db_path, "live", _iso(timedelta(days=30)))
    _insert_code(db_path, "expired", _iso(-timedelta(days=2)))
    _insert_code(db_path, "used", _iso(timedelta(days=1)), used_at=_iso(-timedelta(days=2)))
    _insert_code(
        db_path, "fresh-used", _iso(timedelta(minutes=5)), used_at=_iso(-timedelta(hours=1))
    )
    _insert_code(db_path, "pending", _iso(timedelta(minutes=5)))

    counts = auth.purge_expired(_iso(-timedelta(days=1)))

    assert counts == {"sessions": 1, "login_codes": 2}
    assert _ids(db_path, "sessions") == ["just-expired", "live"]
    assert _ids(db_path, "login_codes") == ["fresh-used", "pending"]


def test_rate_limiter_purges_stale_rows_in_every_bucket(db_path):
    limiter = RateLimiter(db_path)
    with sqlite3.connect(db_path) as connection:
        connection.executemany(
            "INSERT INTO rate_events (bucket, key, created_at) VALUES (?, ?, ?)",
            [
                ("otp_send", "a@example.com", _iso(-timedelta(days=3))),
                ("ip_signup", "1.2.3.4", _iso(-timedelta(days=5))),
                ("ip_signup", "1.2.3.4", _iso(-timedelta(hours=2))),
            ],
        )

    assert limiter.purge_before(_iso(-timedelta(days=2))) == 2
    assert _rows(db_path, "SELECT bucket FROM rate_events") == [("ip_signup",)]


def test_audit_store_purges_old_events(db_path):
    audit = AuditStore(db_path)
    audit.record(action="old", actor_user_id=None)
    audit.record(action="new", actor_user_id=None)
    with sqlite3.connect(db_path) as connection:
        connection.execute("UPDATE audit_events SET created_at = ? WHERE action = 'old'",
                           (_iso(-timedelta(days=400)),))

    assert audit.purge_before(_iso(-timedelta(days=365))) == 1
    assert [e["action"] for e in audit.list()] == ["new"]


def _stores(db_path):
    return {
        "auth": AuthStore(db_path),
        "limiter": RateLimiter(db_path),
        "audit": AuditStore(db_path),
    }


def test_privacy_purge_prunes_and_records_counts(db_path):
    stores = _stores(db_path)
    _insert_session(db_path, "old", _iso(-timedelta(days=2)))
    _insert_code(db_path, "expired", _iso(-timedelta(days=2)))
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "INSERT INTO rate_events (bucket, key, created_at) VALUES ('otp_send', 'x', ?)",
            (_iso(-timedelta(days=3)),),
        )
    stores["audit"].record(action="ancient", actor_user_id=None)
    with sqlite3.connect(db_path) as connection:
        connection.execute("UPDATE audit_events SET created_at = ?", (_iso(-timedelta(days=400)),))

    counts = backup.run_privacy_purge(**stores, audit_days=365, now=NOW)

    assert counts == {"sessions": 1, "login_codes": 1, "rate_events": 1, "audit_events": 1}
    [event] = stores["audit"].list()
    assert event["action"] == "personal_data_pruned"
    assert event["actor_user_id"] is None
    assert event["details"] == {
        **counts, "audit_retention_days": 365, "source": "system",
    }


def test_privacy_purge_records_nothing_when_nothing_deleted(db_path):
    stores = _stores(db_path)
    _insert_session(db_path, "live", _iso(timedelta(days=30)))
    stores["audit"].record(action="recent", actor_user_id=None)

    counts = backup.run_privacy_purge(**stores, audit_days=365, now=NOW + timedelta(days=1))

    assert counts == {"sessions": 0, "login_codes": 0, "rate_events": 0, "audit_events": 0}
    assert [e["action"] for e in stores["audit"].list()] == ["recent"]


def test_privacy_purge_keeps_audit_log_when_retention_disabled(db_path):
    stores = _stores(db_path)
    stores["audit"].record(action="ancient", actor_user_id=None)
    with sqlite3.connect(db_path) as connection:
        connection.execute("UPDATE audit_events SET created_at = ?", (_iso(-timedelta(days=4000)),))

    counts = backup.run_privacy_purge(**stores, audit_days=0, now=NOW)

    assert counts["audit_events"] == 0
    assert [e["action"] for e in stores["audit"].list()] == ["ancient"]


def test_audit_retention_config(monkeypatch):
    assert backup.BackupConfig.from_env().audit_retention_days == 365
    monkeypatch.setenv("AUDIT_RETENTION_DAYS", "0")
    assert backup.BackupConfig.from_env().audit_retention_days == 0
    monkeypatch.setenv("AUDIT_RETENTION_DAYS", "30")
    assert backup.BackupConfig.from_env().audit_retention_days == 30
    monkeypatch.setenv("AUDIT_RETENTION_DAYS", "soon")
    assert backup.BackupConfig.from_env().audit_retention_days == 365


def test_retention_loop_runs_privacy_purge_without_job_retention_or_mongo(
    tmp_path, db_path, monkeypatch
):
    monkeypatch.setattr(backup, "FIRST_RUN_DELAY_SECONDS", 0.01)
    store = JobStore(db_path)
    job_id = store.create_job({})["id"]
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "UPDATE annotation_jobs SET status = 'completed', finished_at = ? WHERE id = ?",
            ("2000-01-01T00:00:00+00:00", job_id),
        )
    AuthStore(db_path)
    _insert_session(db_path, "old", "2000-01-01T00:00:00+00:00")
    client = make_client(tmp_path, job_store=store)

    with TestClient(client.app):
        loop = client.app.state.retention_loop
        assert loop is not None and loop.is_alive()
        deadline = time.monotonic() + 5
        while _ids(db_path, "sessions") and time.monotonic() < deadline:
            time.sleep(0.01)
        assert _ids(db_path, "sessions") == []
        assert store.get_job(job_id) is not None
    assert not loop.is_alive()
