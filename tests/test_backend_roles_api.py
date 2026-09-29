import os
from unittest import mock

from backend import email_sender
from backend.access import BOOTSTRAP_ADMIN_EMAIL
from tests.auth_helpers import (
    make_client,
    second_client,
    signed_in_client,
    worker_headers,
)


def test_me_reports_role(tmp_path):
    client = signed_in_client(tmp_path, email="u@example.com")
    body = client.get("/auth/me").json()
    assert body["role"] == "user"
    assert body["status"] == "active"


def test_bootstrap_admin_me(tmp_path):
    client = signed_in_client(tmp_path, email=BOOTSTRAP_ADMIN_EMAIL)
    assert client.get("/auth/me").json()["role"] == "admin"


def test_user_cannot_mutate_profiles(tmp_path):
    client = signed_in_client(tmp_path, email="u@example.com")
    assert client.post("/profiles", json={"name": "x"}).status_code == 403
    assert client.delete("/profiles/anything").status_code == 403


def test_user_cannot_update_profiles(tmp_path):
    client = signed_in_client(tmp_path, email="u@example.com")
    response = client.put(
        "/profiles/mtb-h37rv",
        json={"profile_id": "mtb-h37rv", "canonical_name": "x", "species_name": "x"},
    )
    assert response.status_code == 403
    assert response.json() == {"detail": "Admin access required"}


def test_user_can_list_profiles(tmp_path):
    client = signed_in_client(tmp_path, email="u@example.com")
    assert client.get("/profiles").status_code == 200


def test_user_cannot_see_workers_health_or_clear_history(tmp_path):
    client = signed_in_client(tmp_path, email="u@example.com")
    assert client.get("/workers").status_code == 403
    assert client.get("/health").status_code == 403
    assert client.delete("/jobs/history").status_code == 403


def test_user_cannot_call_regex_or_backend_info(tmp_path):
    client = signed_in_client(tmp_path, email="u@example.com")
    assert client.post("/regex/from-examples", json={"examples": ["Rv0001"]}).status_code == 403
    assert client.post("/regex/from-description", json={"description": "x"}).status_code == 403
    assert client.get("/backend-info").status_code == 403


def test_admin_can_reach_admin_routes(tmp_path):
    client = signed_in_client(tmp_path, email=BOOTSTRAP_ADMIN_EMAIL)
    assert client.get("/workers").status_code == 200
    assert client.get("/health").status_code == 200
    assert client.delete("/jobs/history").status_code == 200
    assert client.get("/backend-info").status_code == 200
    assert client.post("/regex/from-examples", json={"examples": ["Rv0001"]}).status_code == 200


def test_unauthenticated_admin_routes_return_401(tmp_path):
    client = make_client(tmp_path)
    assert client.get("/health").status_code == 401
    assert client.get("/backend-info").status_code == 401


def test_healthz_is_public_and_minimal(tmp_path):
    client = signed_in_client(tmp_path, email="u@example.com")
    client.cookies.clear()
    body = client.get("/healthz").json()
    assert body == {"status": "ok"}


def test_suspended_user_is_rejected(tmp_path):
    client, store = signed_in_client(tmp_path, email="u@example.com", return_store=True)
    user = store.get_user_by_email("u@example.com")
    store.set_status(user["id"], "suspended")
    response = client.get("/auth/me")
    assert response.status_code == 403
    assert response.json() == {"detail": "Account suspended"}


def test_suspended_admin_loses_admin_access(tmp_path):
    client, store = signed_in_client(tmp_path, email=BOOTSTRAP_ADMIN_EMAIL, return_store=True)
    user = store.get_user_by_email(BOOTSTRAP_ADMIN_EMAIL)
    store.set_status(user["id"], "suspended")
    assert client.get("/workers").status_code == 403


def test_new_signup_is_active_user_immediately(tmp_path):
    client, store = signed_in_client(tmp_path, email="new@example.com", return_store=True)
    user = store.get_user_by_email("new@example.com")
    assert (user["role"], user["status"]) == ("user", "active")
    assert client.get("/auth/me").status_code == 200


def test_suspended_user_gets_no_login_code(tmp_path):
    client, store = signed_in_client(tmp_path, email="u@example.com", return_store=True)
    store.set_status(store.get_user_by_email("u@example.com")["id"], "suspended")
    client.cookies.clear()
    with mock.patch.dict(os.environ, {"EMAIL_BACKEND": "console"}):
        email_sender._CONSOLE_OUTBOX.clear()
        login = client.post("/auth/login", json={"email": "u@example.com"})
        signup = client.post("/auth/signup", json={"email": "u@example.com"})
    assert login.status_code == 200
    assert signup.status_code == 200
    assert email_sender._CONSOLE_OUTBOX == []


def test_verify_rejects_suspended_user_with_outstanding_code(tmp_path):
    client, store = signed_in_client(tmp_path, email="u@example.com", return_store=True)
    client.cookies.clear()
    with mock.patch.dict(os.environ, {"EMAIL_BACKEND": "console"}):
        email_sender._CONSOLE_OUTBOX.clear()
        client.post("/auth/login", json={"email": "u@example.com"})
        code = email_sender._CONSOLE_OUTBOX[-1]["code"]
    store.set_status(store.get_user_by_email("u@example.com")["id"], "suspended")
    response = client.post("/auth/verify", json={"email": "u@example.com", "code": code})
    assert response.status_code == 403
    assert "ga_session" not in response.cookies


def test_verify_marks_last_login(tmp_path):
    _client, store = signed_in_client(tmp_path, email="u@example.com", return_store=True)
    assert store.get_user_by_email("u@example.com")["last_login_at"] is not None


def test_second_client_shares_app_with_distinct_identity(tmp_path):
    first = signed_in_client(tmp_path, email="a@example.com")
    other = second_client(first, "b@example.com")
    assert other.app is first.app
    assert first.get("/auth/me").json()["email"] == "a@example.com"
    assert other.get("/auth/me").json()["email"] == "b@example.com"


def test_worker_token_routes_do_not_need_a_session(tmp_path):
    client = make_client(tmp_path)
    response = client.get("/jobs/queue-summary", headers=worker_headers())
    assert response.status_code == 200
    assert client.get("/jobs/queue-summary").status_code == 401
