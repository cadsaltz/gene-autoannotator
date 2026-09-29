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
