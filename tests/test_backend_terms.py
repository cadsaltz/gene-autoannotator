from datetime import datetime

from backend import email_sender
from tests.auth_helpers import admin_client, make_client


def _signup(client, body):
    email_sender._CONSOLE_OUTBOX.clear()
    return client.post("/auth/signup", json=body)


def test_signup_without_accept_terms_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("EMAIL_BACKEND", "console")
    client = make_client(tmp_path)

    response = _signup(client, {"email": "a@example.com"})

    assert response.status_code == 422
    assert client.auth_store.get_user_by_email("a@example.com") is None
    assert email_sender._CONSOLE_OUTBOX == []


def test_signup_with_accept_terms_false_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("EMAIL_BACKEND", "console")
    client = make_client(tmp_path)

    response = _signup(client, {"email": "a@example.com", "accept_terms": False})

    assert response.status_code == 422
    assert client.auth_store.get_user_by_email("a@example.com") is None


def test_signup_rejects_non_boolean_accept_terms(tmp_path, monkeypatch):
    monkeypatch.setenv("EMAIL_BACKEND", "console")
    client = make_client(tmp_path)

    for value in ("true", 1, "yes"):
        response = _signup(client, {"email": "a@example.com", "accept_terms": value})
        assert response.status_code == 422, value
    assert client.auth_store.get_user_by_email("a@example.com") is None


def test_signup_with_accept_terms_records_default_version(tmp_path, monkeypatch):
    monkeypatch.setenv("EMAIL_BACKEND", "console")
    monkeypatch.delenv("TERMS_VERSION", raising=False)
    client = make_client(tmp_path)

    response = _signup(client, {"email": "a@example.com", "accept_terms": True})

    assert response.status_code == 200
    user = client.auth_store.get_user_by_email("a@example.com")
    assert user["terms_version"] == "draft-2026-09"
    assert datetime.fromisoformat(user["terms_accepted_at"]) is not None
    assert user["terms_accepted_at"] == user["created_at"]


def test_signup_records_terms_version_from_env(tmp_path, monkeypatch):
    monkeypatch.setenv("EMAIL_BACKEND", "console")
    monkeypatch.setenv("TERMS_VERSION", "2027-01")
    client = make_client(tmp_path)

    _signup(client, {"email": "a@example.com", "accept_terms": True})

    assert client.auth_store.get_user_by_email("a@example.com")["terms_version"] == "2027-01"


def test_repeat_signup_does_not_rewrite_existing_consent(tmp_path, monkeypatch):
    monkeypatch.setenv("EMAIL_BACKEND", "console")
    client = make_client(tmp_path)
    legacy = client.auth_store.create_user(email="old@example.com", username=None)

    response = _signup(client, {"email": "old@example.com", "accept_terms": True})

    assert response.status_code == 200
    user = client.auth_store.get_user(legacy["id"])
    assert user["terms_version"] is None
    assert user["terms_accepted_at"] is None


def _verify_last_code(client, email):
    code = email_sender._CONSOLE_OUTBOX[-1]["code"]
    return client.post("/auth/verify", json={"email": email, "code": code})


def test_verifying_signup_code_records_consent_for_pre_consent_account(tmp_path, monkeypatch):
    monkeypatch.setenv("EMAIL_BACKEND", "console")
    monkeypatch.setenv("TERMS_VERSION", "2027-01")
    client = make_client(tmp_path)
    legacy = client.auth_store.create_user(email="old@example.com", username=None)

    _signup(client, {"email": "old@example.com", "accept_terms": True})
    assert client.auth_store.get_user(legacy["id"])["terms_version"] is None
    assert _verify_last_code(client, "old@example.com").status_code == 200

    user = client.auth_store.get_user(legacy["id"])
    assert user["terms_version"] == "2027-01"
    assert user["terms_accepted_at"]


def test_verifying_signup_code_keeps_existing_consent(tmp_path, monkeypatch):
    monkeypatch.setenv("EMAIL_BACKEND", "console")
    client = make_client(tmp_path)
    _signup(client, {"email": "a@example.com", "accept_terms": True})
    before = client.auth_store.get_user_by_email("a@example.com")

    _signup(client, {"email": "a@example.com", "accept_terms": True})
    assert _verify_last_code(client, "a@example.com").status_code == 200

    after = client.auth_store.get_user_by_email("a@example.com")
    assert after["terms_version"] == before["terms_version"]
    assert after["terms_accepted_at"] == before["terms_accepted_at"]


def test_verifying_login_code_does_not_record_consent(tmp_path, monkeypatch):
    monkeypatch.setenv("EMAIL_BACKEND", "console")
    client = make_client(tmp_path)
    legacy = client.auth_store.create_user(email="old@example.com", username=None)

    email_sender._CONSOLE_OUTBOX.clear()
    client.post("/auth/login", json={"email": "old@example.com"})
    assert _verify_last_code(client, "old@example.com").status_code == 200

    assert client.auth_store.get_user(legacy["id"])["terms_version"] is None


def test_rejected_consent_does_not_consume_ip_signup_limit(tmp_path, monkeypatch):
    monkeypatch.setenv("EMAIL_BACKEND", "console")
    monkeypatch.setenv("IP_SIGNUPS_PER_DAY", "1")
    client = make_client(tmp_path)

    assert _signup(client, {"email": "a@example.com"}).status_code == 422
    assert _signup(client, {"email": "a@example.com", "accept_terms": True}).status_code == 200


def test_admin_users_list_exposes_terms_fields(tmp_path, monkeypatch):
    monkeypatch.setenv("EMAIL_BACKEND", "console")
    client = make_client(tmp_path)
    admin = admin_client(client.app)
    client.auth_store.create_user(email="legacy@example.com", username=None)

    rows = {row["email"]: row for row in admin.get("/admin/users").json()["users"]}

    assert rows["legacy@example.com"]["terms_version"] is None
    assert rows["legacy@example.com"]["terms_accepted_at"] is None
    admin_row = next(row for row in rows.values() if row["email"] != "legacy@example.com")
    assert admin_row["terms_version"] == "draft-2026-09"
    assert admin_row["terms_accepted_at"]
