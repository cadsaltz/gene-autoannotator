from backend.auth_store import AuthStore


def test_create_and_get_user_by_email(tmp_path):
    store = AuthStore(tmp_path / "jobs.sqlite3")
    user = store.create_user(email="a@example.com", username="alice")
    assert user["email"] == "a@example.com"
    assert user["username"] == "alice"
    assert user["email_verified"] is False
    assert store.get_user_by_email("A@example.com")["id"] == user["id"]


def test_login_code_consume_once(tmp_path):
    store = AuthStore(tmp_path / "jobs.sqlite3")
    store.create_user(email="a@example.com", username=None)
    store.create_login_code(
        email="a@example.com",
        purpose="signup",
        code_hash="hash1",
        expires_at="2099-01-01T00:00:00+00:00",
    )
    first = store.consume_login_code(email="a@example.com", code_hash="hash1")
    second = store.consume_login_code(email="a@example.com", code_hash="hash1")
    assert first["email"] == "a@example.com"
    assert second is None


def test_session_round_trip(tmp_path):
    store = AuthStore(tmp_path / "jobs.sqlite3")
    user = store.create_user(email="a@example.com", username=None)
    store.mark_email_verified(user["id"])
    store.create_session(
        user_id=user["id"],
        token_hash="sess",
        expires_at="2099-01-01T00:00:00+00:00",
        ip="127.0.0.1",
    )
    found = store.get_session_user("sess")
    assert found["id"] == user["id"]
    assert found["email_verified"] is True
