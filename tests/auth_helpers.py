"""Shared OTP sign-in helpers for API tests that hit session-gated routes."""

import os
from unittest import mock

from fastapi.testclient import TestClient

from backend import email_sender
from backend.access import BOOTSTRAP_ADMIN_EMAIL
from backend.annotation_store import InMemoryAnnotationStore
from backend.api import create_app
from backend.auth_store import AuthStore
from backend.batch_store import BatchStore
from backend.job_store import JobStore
from backend.profile_store import LocalProfileStore

WORKER_TOKEN = "test-token"


def sign_in(client: TestClient, email: str = "tester@example.com") -> TestClient:
    with mock.patch.dict(os.environ, {"EMAIL_BACKEND": "console"}):
        email_sender._CONSOLE_OUTBOX.clear()
        client.post("/auth/signup", json={"email": email})
        code = email_sender._CONSOLE_OUTBOX[-1]["code"]
        verify = client.post("/auth/verify", json={"email": email, "code": code})
    assert verify.status_code == 200
    return client


def authed_client(app, **kwargs) -> TestClient:
    return sign_in(TestClient(app, **kwargs))


def admin_client(app, **kwargs) -> TestClient:
    return sign_in(TestClient(app, **kwargs), email=BOOTSTRAP_ADMIN_EMAIL)


def make_client(tmp_path, **app_kwargs) -> TestClient:
    db_path = tmp_path / "jobs.sqlite3"
    job_store = app_kwargs.pop("job_store", None) or JobStore(db_path)
    auth_store = app_kwargs.pop("auth_store", None) or AuthStore(job_store.db_path)
    app_kwargs.setdefault("batch_store", BatchStore(job_store.db_path))
    app_kwargs.setdefault("profile_store", LocalProfileStore(tmp_path / "profiles"))
    app_kwargs.setdefault("annotation_store", InMemoryAnnotationStore())
    app_kwargs.setdefault("start_worker", False)
    app_kwargs.setdefault("worker_api_token", WORKER_TOKEN)
    app = create_app(job_store=job_store, auth_store=auth_store, **app_kwargs)
    client = TestClient(app)
    client.auth_store = auth_store
    return client


def signed_in_client(tmp_path, email: str = "tester@example.com", return_store: bool = False):
    client = sign_in(make_client(tmp_path), email=email)
    if return_store:
        return client, client.auth_store
    return client


def second_client(existing_client: TestClient, email: str) -> TestClient:
    client = TestClient(existing_client.app)
    client.auth_store = getattr(existing_client, "auth_store", None)
    return sign_in(client, email=email)


def worker_headers() -> dict:
    return {"Authorization": f"Bearer {WORKER_TOKEN}"}
