from fastapi.testclient import TestClient

from backend.api import create_app
from backend.auth_store import AuthStore
from backend.job_store import JobStore
from backend import email_sender


def _app(tmp_path, monkeypatch):
    monkeypatch.setenv("EMAIL_BACKEND", "console")
    email_sender._CONSOLE_OUTBOX.clear()
    db = tmp_path / "jobs.sqlite3"
    return create_app(
        job_store=JobStore(db),
        auth_store=AuthStore(db),
        worker_capacity_required=False,
    )


def test_signup_sends_otp_and_verify_sets_cookie(tmp_path, monkeypatch):
    client = TestClient(_app(tmp_path, monkeypatch))
    response = client.post("/auth/signup", json={"email": "a@example.com", "username": "alice"})
    assert response.status_code == 200
    assert email_sender._CONSOLE_OUTBOX
    code = email_sender._CONSOLE_OUTBOX[-1]["code"]

    verify = client.post("/auth/verify", json={"email": "a@example.com", "code": code})
    assert verify.status_code == 200
    assert "ga_session" in verify.cookies

    me = client.get("/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == "a@example.com"
    assert me.json()["email_verified"] is True


def test_verify_rejects_wrong_code(tmp_path, monkeypatch):
    client = TestClient(_app(tmp_path, monkeypatch))
    client.post("/auth/signup", json={"email": "a@example.com"})
    response = client.post("/auth/verify", json={"email": "a@example.com", "code": "000000"})
    assert response.status_code == 401


def test_login_unknown_email_still_returns_ok(tmp_path, monkeypatch):
    client = TestClient(_app(tmp_path, monkeypatch))
    response = client.post("/auth/login", json={"email": "missing@example.com"})
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert email_sender._CONSOLE_OUTBOX == []


def test_logout_clears_session(tmp_path, monkeypatch):
    client = TestClient(_app(tmp_path, monkeypatch))
    client.post("/auth/signup", json={"email": "a@example.com", "username": "alice"})
    code = email_sender._CONSOLE_OUTBOX[-1]["code"]
    client.post("/auth/verify", json={"email": "a@example.com", "code": code})

    logout = client.post("/auth/logout")
    assert logout.status_code == 204

    me = client.get("/auth/me")
    assert me.status_code == 401


def test_create_job_requires_session(tmp_path, monkeypatch):
    client = TestClient(_app(tmp_path, monkeypatch))
    response = client.post("/jobs", json={"profile": "mtb-h37rv", "locus": "Rv0001"})
    assert response.status_code == 401


def test_create_job_allowed_when_signed_in(tmp_path, monkeypatch):
    client = TestClient(_app(tmp_path, monkeypatch))
    client.post("/auth/signup", json={"email": "a@example.com"})
    code = email_sender._CONSOLE_OUTBOX[-1]["code"]
    client.post("/auth/verify", json={"email": "a@example.com", "code": code})
    response = client.post("/jobs", json={"profile": "mtb-h37rv", "locus": "Rv0001"})
    assert response.status_code == 201
