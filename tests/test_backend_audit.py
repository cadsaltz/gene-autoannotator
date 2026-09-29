import logging
import os
import sqlite3
from unittest import mock

import pytest

from backend import email_sender
from backend.access import BOOTSTRAP_ADMIN_EMAIL
from backend.audit_store import AuditStore
from tests.auth_helpers import make_client, second_client, sign_in, signed_in_client

JOB = {"profile": "mtb-h37rv", "locus": "Rv0001"}
BATCH = {
    "profile": "mtb-h37rv",
    "entries": [{"input": "Rv0001"}, {"input": "Rv0002"}],
    "allow_online_name_lookup": False,
}
PROFILE = {
    "profile_id": "custom-profile",
    "canonical_name": "Custom organism",
    "species_name": "Custom organism",
}


@pytest.fixture(autouse=True)
def isolate_env(tmp_path, monkeypatch):
    monkeypatch.setenv("PROFILES_DIR", str(tmp_path / "profiles"))
    monkeypatch.delenv("MONGO_URI", raising=False)
    monkeypatch.delenv("MONGODB_URI", raising=False)
    for name in ("MAX_QUEUED_JOBS", "USER_MAX_ACTIVE_JOBS", "USER_MAX_JOBS_PER_DAY", "USER_MAX_BATCH_SIZE"):
        monkeypatch.delenv(name, raising=False)


def _events(admin, **params):
    response = admin.get("/admin/audit", params=params)
    assert response.status_code == 200
    return response.json()["events"]


def _user_id(client, email):
    return client.auth_store.get_user_by_email(email)["id"]


def test_submit_is_audited_with_ip(tmp_path):
    alice = signed_in_client(tmp_path, email="alice@example.com")
    job_id = alice.post("/jobs", json=JOB).json()["job_id"]
    admin = second_client(alice, email=BOOTSTRAP_ADMIN_EMAIL)
    events = _events(admin, action="job_submit")
    assert len(events) == 1
    event = events[0]
    assert event["actor_user_id"] == _user_id(alice, "alice@example.com")
    assert event["actor_email"] == "alice@example.com"
    assert event["target_type"] == "job"
    assert event["target_id"] == job_id
    assert event["ip"] == "testclient"
    assert set(event) == {
        "id", "created_at", "action", "actor_user_id", "actor_email",
        "target_type", "target_id", "ip", "details",
    }


def test_users_cannot_read_audit(tmp_path):
    alice = signed_in_client(tmp_path, email="alice@example.com")
    assert alice.get("/admin/audit").status_code == 403


def test_anonymous_cannot_read_audit(tmp_path):
    client = make_client(tmp_path)
    assert client.get("/admin/audit").status_code == 401


def test_signup_and_login_audited(tmp_path):
    alice = signed_in_client(tmp_path, email="alice@example.com")
    admin = second_client(alice, email=BOOTSTRAP_ADMIN_EMAIL)
    alice_id = _user_id(alice, "alice@example.com")
    actions = {e["action"] for e in _events(admin, user_id=alice_id)}
    assert {"signup", "login_code_sent", "login"} <= actions


def test_signup_recorded_only_for_new_users(tmp_path):
    alice = signed_in_client(tmp_path, email="alice@example.com")
    sign_in(alice, email="alice@example.com")
    admin = second_client(alice, email=BOOTSTRAP_ADMIN_EMAIL)
    alice_id = _user_id(alice, "alice@example.com")
    signups = _events(admin, action="signup", user_id=alice_id)
    assert len(signups) == 1
    assert len(_events(admin, action="login_code_sent", user_id=alice_id)) == 2


def test_login_code_sent_never_stores_code(tmp_path):
    client = make_client(tmp_path)
    with mock.patch.dict(os.environ, {"EMAIL_BACKEND": "console"}):
        email_sender._CONSOLE_OUTBOX.clear()
        client.post("/auth/signup", json={"email": "alice@example.com"})
        code = email_sender._CONSOLE_OUTBOX[-1]["code"]
    admin = second_client(client, email=BOOTSTRAP_ADMIN_EMAIL)
    events = _events(admin, action="login_code_sent", user_id=_user_id(client, "alice@example.com"))
    assert len(events) == 1
    assert code not in str(events[0])
    with sqlite3.connect(tmp_path / "jobs.sqlite3") as connection:
        rows = connection.execute("SELECT * FROM audit_events").fetchall()
    assert all(code not in str(row) for row in rows)


def test_login_code_not_recorded_for_unknown_or_suspended_email(tmp_path):
    client, store = signed_in_client(tmp_path, email="alice@example.com", return_store=True)
    alice_id = _user_id(client, "alice@example.com")
    store.set_status(alice_id, "suspended")
    admin = second_client(client, email=BOOTSTRAP_ADMIN_EMAIL)
    before = len(_events(admin, action="login_code_sent"))
    with mock.patch.dict(os.environ, {"EMAIL_BACKEND": "console"}):
        client.post("/auth/login", json={"email": "nobody@example.com"})
        client.post("/auth/login", json={"email": "alice@example.com"})
    assert len(_events(admin, action="login_code_sent")) == before


def test_logout_audited(tmp_path):
    alice = signed_in_client(tmp_path, email="alice@example.com")
    alice_id = _user_id(alice, "alice@example.com")
    assert alice.post("/auth/logout").status_code == 204
    admin = second_client(alice, email=BOOTSTRAP_ADMIN_EMAIL)
    events = _events(admin, action="logout")
    assert [e["actor_user_id"] for e in events] == [alice_id]


def test_batch_submit_audited_with_job_count(tmp_path):
    alice = signed_in_client(tmp_path, email="alice@example.com")
    response = alice.post("/batches", json=BATCH)
    assert response.status_code == 201
    admin = second_client(alice, email=BOOTSTRAP_ADMIN_EMAIL)
    events = _events(admin, action="batch_submit")
    assert len(events) == 1
    assert events[0]["target_type"] == "batch"
    assert events[0]["target_id"] == response.json()["batch_id"]
    assert events[0]["details"] == {"job_count": 2}


def test_job_cancel_audited(tmp_path):
    alice = signed_in_client(tmp_path, email="alice@example.com")
    job_id = alice.post("/jobs", json=JOB).json()["job_id"]
    assert alice.post(f"/jobs/{job_id}/cancel").status_code == 200
    admin = second_client(alice, email=BOOTSTRAP_ADMIN_EMAIL)
    events = _events(admin, action="job_cancel")
    assert len(events) == 1
    assert events[0]["target_id"] == job_id
    assert events[0]["details"]["previous_status"] == "queued"


def test_profile_mutations_audited(tmp_path):
    admin = signed_in_client(tmp_path, email=BOOTSTRAP_ADMIN_EMAIL)
    assert admin.post("/profiles", json=PROFILE).status_code == 201
    assert admin.put(
        "/profiles/custom-profile", json={**PROFILE, "canonical_name": "Edited"}
    ).status_code == 200
    assert admin.delete("/profiles/custom-profile").status_code == 200
    events = [e for e in _events(admin) if e["target_type"] == "profile"]
    assert [e["action"] for e in events] == ["profile_delete", "profile_update", "profile_create"]
    assert all(e["target_id"] == "custom-profile" for e in events)


def test_events_newest_first_and_limited(tmp_path):
    alice = signed_in_client(tmp_path, email="alice@example.com")
    first = alice.post("/jobs", json=JOB).json()["job_id"]
    second = alice.post("/jobs", json=JOB).json()["job_id"]
    admin = second_client(alice, email=BOOTSTRAP_ADMIN_EMAIL)
    events = _events(admin, action="job_submit")
    assert [e["target_id"] for e in events] == [second, first]
    assert len(_events(admin, limit=1)) == 1


def test_limit_bounds(tmp_path):
    admin = signed_in_client(tmp_path, email=BOOTSTRAP_ADMIN_EMAIL)
    assert admin.get("/admin/audit", params={"limit": 1000}).status_code == 200
    assert admin.get("/admin/audit", params={"limit": 1001}).status_code == 422
    assert admin.get("/admin/audit", params={"limit": 0}).status_code == 422


def test_user_id_filter_matches_actor_or_user_target(tmp_path):
    alice = signed_in_client(tmp_path, email="alice@example.com")
    admin = second_client(alice, email=BOOTSTRAP_ADMIN_EMAIL)
    alice_id = _user_id(alice, "alice@example.com")
    admin_id = _user_id(alice, BOOTSTRAP_ADMIN_EMAIL)
    audit = alice.app.state.audit_store
    audit.record(
        action="role_change", actor_user_id=admin_id, target_type="user",
        target_id=alice_id, details={"previous": "user", "new": "admin"},
    )
    audit.record(
        action="job_cancel", actor_user_id=admin_id, target_type="job", target_id=alice_id,
    )
    events = _events(admin, user_id=alice_id)
    role_changes = [e for e in events if e["action"] == "role_change"]
    assert len(role_changes) == 1
    assert role_changes[0]["actor_email"] == BOOTSTRAP_ADMIN_EMAIL
    assert not any(e["action"] == "job_cancel" for e in events)
    assert all(
        e["actor_user_id"] == alice_id or (e["target_type"] == "user" and e["target_id"] == alice_id)
        for e in events
    )


def test_actor_email_null_after_user_deleted(tmp_path):
    alice, store = signed_in_client(tmp_path, email="alice@example.com", return_store=True)
    alice_id = _user_id(alice, "alice@example.com")
    alice.post("/jobs", json=JOB)
    store.delete_user(alice_id)
    admin = second_client(alice, email=BOOTSTRAP_ADMIN_EMAIL)
    events = _events(admin, action="job_submit")
    assert events[0]["actor_user_id"] == alice_id
    assert events[0]["actor_email"] is None


def test_create_app_accepts_injected_audit_store(tmp_path):
    audit = AuditStore(tmp_path / "audit.sqlite3")
    alice = sign_in(make_client(tmp_path, audit_store=audit), email="alice@example.com")
    assert alice.app.state.audit_store is audit
    alice.post("/jobs", json=JOB)
    assert [e["action"] for e in audit.list(action="job_submit")] == ["job_submit"]


class BrokenAuditStore(AuditStore):
    broken = False

    def _connect(self):
        if self.broken:
            raise sqlite3.OperationalError("disk I/O error")
        return super()._connect()


def test_audit_write_failure_does_not_break_requests(tmp_path, caplog):
    audit = BrokenAuditStore(tmp_path / "audit.sqlite3")
    audit.broken = True
    client = make_client(tmp_path, audit_store=audit)
    with caplog.at_level(logging.WARNING, logger="backend.audit_store"):
        sign_in(client, email="alice@example.com")
        assert client.post("/jobs", json=JOB).status_code == 201
        assert client.post("/auth/logout").status_code == 204
    assert any("audit" in record.getMessage().lower() for record in caplog.records)
    assert all(record.levelno == logging.WARNING for record in caplog.records
               if record.name == "backend.audit_store")


def test_store_list_filters(tmp_path):
    audit = AuditStore(tmp_path / "audit.sqlite3")
    audit.record(action="login", actor_user_id="u1", ip="1.2.3.4")
    audit.record(action="job_submit", actor_user_id="u1", target_type="job", target_id="j1",
                 details={"job_id": "j1"})
    audit.record(action="job_submit", actor_user_id="u2", target_type="job", target_id="j2")
    assert [e["target_id"] for e in audit.list(action="job_submit")] == ["j2", "j1"]
    assert [e["action"] for e in audit.list(actor_user_id="u1")] == ["job_submit", "login"]
    assert [e["actor_user_id"] for e in audit.list(target_id="j1")] == ["u1"]
    assert audit.list(target_id="j1")[0]["details"] == {"job_id": "j1"}
    assert audit.list(action="login")[0]["details"] == {}
    assert audit.list(action="login")[0]["actor_email"] is None
    assert len(audit.list(limit=2)) == 2
