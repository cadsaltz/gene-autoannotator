"""Shared OTP sign-in helpers for API tests that hit session-gated routes."""

from fastapi.testclient import TestClient

from backend import email_sender


def sign_in(client: TestClient, email: str = "tester@example.com") -> TestClient:
    email_sender._CONSOLE_OUTBOX.clear()
    client.post("/auth/signup", json={"email": email})
    code = email_sender._CONSOLE_OUTBOX[-1]["code"]
    verify = client.post("/auth/verify", json={"email": email, "code": code})
    assert verify.status_code == 200
    return client


def authed_client(app, **kwargs) -> TestClient:
    return sign_in(TestClient(app, **kwargs))
