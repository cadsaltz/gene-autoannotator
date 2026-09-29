import sqlite3

from backend.auth_store import AuthStore
from backend.access import BOOTSTRAP_ADMIN_EMAIL, is_admin


def _store(tmp_path):
    return AuthStore(tmp_path / "db.sqlite3")


def test_new_users_default_to_user_role_and_active(tmp_path):
    user = _store(tmp_path).create_user(email="a@example.com", username=None)
    assert user["role"] == "user"
    assert user["status"] == "active"


def test_bootstrap_email_is_admin_on_creation_case_insensitive(tmp_path):
    user = _store(tmp_path).create_user(email=BOOTSTRAP_ADMIN_EMAIL.upper(), username=None)
    assert user["role"] == "admin"
    assert is_admin(user)


def test_bootstrap_admin_role_can_be_changed_and_persists(tmp_path):
    store = _store(tmp_path)
    user = store.create_user(email=BOOTSTRAP_ADMIN_EMAIL, username=None)
    store.set_role(user["id"], "user")
    reopened = AuthStore(tmp_path / "db.sqlite3")
    assert reopened.get_user(user["id"])["role"] == "user"


def test_migration_promotes_existing_bootstrap_user_only_when_no_admin(tmp_path):
    store = _store(tmp_path)
    user = store.create_user(email=BOOTSTRAP_ADMIN_EMAIL, username=None)
    store.set_role(user["id"], "user")
    other = store.create_user(email="boss@example.com", username=None)
    store.set_role(other["id"], "admin")
    AuthStore(tmp_path / "db.sqlite3")  # reopen runs migration
    assert store.get_user(user["id"])["role"] == "user"


def test_migration_promotes_bootstrap_user_in_legacy_database(tmp_path):
    db_path = tmp_path / "db.sqlite3"
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            CREATE TABLE users (
                id TEXT PRIMARY KEY,
                email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                username TEXT,
                email_verified INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            "INSERT INTO users VALUES ('u1', ?, NULL, 1, '2026-01-01T00:00:00+00:00')",
            (BOOTSTRAP_ADMIN_EMAIL,),
        )
        connection.execute(
            "INSERT INTO users VALUES ('u2', 'a@example.com', NULL, 1, '2026-01-01T00:00:00+00:00')"
        )
    store = AuthStore(db_path)
    assert store.get_user("u1")["role"] == "admin"
    assert store.get_user("u2")["role"] == "user"
    assert store.get_user("u2")["status"] == "active"


def test_invalid_role_rejected(tmp_path):
    store = _store(tmp_path)
    user = store.create_user(email="a@example.com", username=None)
    try:
        store.set_role(user["id"], "superuser")
        raise AssertionError("expected ValueError")
    except ValueError:
        pass


def test_revoke_sessions_removes_all_sessions(tmp_path):
    store = _store(tmp_path)
    user = store.create_user(email="a@example.com", username=None)
    store.create_session(user_id=user["id"], token_hash="h1", expires_at="2999-01-01T00:00:00+00:00", ip=None)
    store.create_session(user_id=user["id"], token_hash="h2", expires_at="2999-01-01T00:00:00+00:00", ip=None)
    assert store.revoke_sessions(user["id"]) == 2
    assert store.get_session_user("h1") is None


def test_invalid_status_rejected(tmp_path):
    store = _store(tmp_path)
    user = store.create_user(email="a@example.com", username=None)
    try:
        store.set_status(user["id"], "pending")
        raise AssertionError("expected ValueError")
    except ValueError:
        pass
