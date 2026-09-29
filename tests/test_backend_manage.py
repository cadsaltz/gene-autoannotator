import subprocess
import sys
from pathlib import Path

import pytest

from backend import db_path, manage
from backend.audit_store import AuditStore
from backend.auth_store import AuthStore

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def db(tmp_path):
    return tmp_path / "jobs.sqlite3"


@pytest.fixture
def auth(db):
    return AuthStore(db)


def _events(db, action=None):
    return AuditStore(db).list(action=action)


def _session(auth, user_id, token="tok"):
    auth.create_session(
        user_id=user_id, token_hash=token, expires_at="2999-01-01T00:00:00+00:00", ip=None
    )


def test_set_role_changes_role_and_audits(db, auth, capsys):
    user = auth.create_user(email="a@example.com", username=None)

    assert manage.main(["--db", str(db), "set-role", "a@example.com", "admin"]) == 0

    assert auth.get_user(user["id"])["role"] == "admin"
    [event] = _events(db, "role_change")
    assert event["actor_user_id"] is None
    assert event["target_type"] == "user"
    assert event["target_id"] == user["id"]
    assert event["details"] == {"from": "user", "to": "admin", "source": "cli"}
    assert "a@example.com" in capsys.readouterr().out


def test_email_lookup_is_case_insensitive(db, auth):
    user = auth.create_user(email="a@example.com", username=None)

    assert manage.main(["--db", str(db), "set-role", "  A@Example.COM ", "admin"]) == 0

    assert auth.get_user(user["id"])["role"] == "admin"


def test_unknown_email_exits_1_with_message(db, auth, capsys):
    assert manage.main(["--db", str(db), "set-role", "nobody@example.com", "admin"]) == 1

    err = capsys.readouterr().err
    assert "nobody@example.com" in err
    assert "no user" in err.lower()
    assert _events(db) == []


@pytest.mark.parametrize(
    "argv",
    [
        ["set-role", "a@example.com", "superuser"],
        ["set-status", "a@example.com", "banned"],
    ],
)
def test_invalid_value_exits_1_without_changes(db, auth, capsys, argv):
    user = auth.create_user(email="a@example.com", username=None)

    assert manage.main(["--db", str(db), *argv]) == 1

    err = capsys.readouterr().err
    assert argv[2] in err
    unchanged = auth.get_user(user["id"])
    assert (unchanged["role"], unchanged["status"]) == ("user", "active")
    assert _events(db) == []


def test_usage_errors_exit_2(db):
    with pytest.raises(SystemExit) as missing_command:
        manage.main(["--db", str(db)])
    assert missing_command.value.code == 2

    with pytest.raises(SystemExit) as missing_arg:
        manage.main(["--db", str(db), "set-role", "a@example.com"])
    assert missing_arg.value.code == 2


def test_missing_database_exits_1_without_creating_it(tmp_path, capsys):
    missing = tmp_path / "nope" / "jobs.sqlite3"

    assert manage.main(["--db", str(missing), "list-users"]) == 1

    assert str(missing) in capsys.readouterr().err
    assert not missing.exists()


def test_unchanged_role_is_a_noop(db, auth, capsys):
    auth.create_user(email="a@example.com", username=None)

    assert manage.main(["--db", str(db), "set-role", "a@example.com", "user"]) == 0

    assert "already" in capsys.readouterr().out
    assert _events(db) == []


def test_suspend_revokes_sessions_and_audits(db, auth):
    user = auth.create_user(email="a@example.com", username=None)
    _session(auth, user["id"], "t1")
    _session(auth, user["id"], "t2")

    assert manage.main(["--db", str(db), "set-status", "a@example.com", "suspended"]) == 0

    assert auth.get_user(user["id"])["status"] == "suspended"
    assert auth.get_session_user("t1") is None
    [status_event] = _events(db, "status_change")
    assert status_event["details"] == {"from": "active", "to": "suspended", "source": "cli"}
    assert status_event["actor_user_id"] is None
    [revoke_event] = _events(db, "sessions_revoked")
    assert revoke_event["details"] == {"count": 2, "source": "cli"}
    assert revoke_event["target_id"] == user["id"]


def test_reactivate_does_not_revoke_sessions(db, auth):
    user = auth.create_user(email="a@example.com", username=None, status="suspended")
    _session(auth, user["id"])

    assert manage.main(["--db", str(db), "set-status", "a@example.com", "active"]) == 0

    assert auth.get_user(user["id"])["status"] == "active"
    assert auth.get_session_user("tok") is not None
    assert _events(db, "sessions_revoked") == []


def test_revoke_sessions_command(db, auth, capsys):
    user = auth.create_user(email="a@example.com", username=None)
    _session(auth, user["id"])

    assert manage.main(["--db", str(db), "revoke-sessions", "a@example.com"]) == 0

    assert auth.get_session_user("tok") is None
    assert auth.get_user(user["id"])["status"] == "active"
    [event] = _events(db, "sessions_revoked")
    assert event["details"] == {"count": 1, "source": "cli"}
    assert event["actor_user_id"] is None
    assert event["target_type"] == "user"
    assert "1" in capsys.readouterr().out


def test_demoting_last_admin_is_allowed_with_warning(db, auth, capsys):
    admin = auth.create_user(email="solavolantes@gmail.com", username=None)
    assert admin["role"] == "admin"

    assert manage.main(["--db", str(db), "set-role", "solavolantes@gmail.com", "user"]) == 0

    assert auth.get_user(admin["id"])["role"] == "user"
    assert "no active admins" in capsys.readouterr().err.lower()


def test_suspending_last_admin_warns(db, auth, capsys):
    auth.create_user(email="solavolantes@gmail.com", username=None)

    assert manage.main(
        ["--db", str(db), "set-status", "solavolantes@gmail.com", "suspended"]
    ) == 0

    assert "no active admins" in capsys.readouterr().err.lower()


def test_no_warning_when_another_admin_remains(db, auth, capsys):
    auth.create_user(email="solavolantes@gmail.com", username=None)
    other = auth.create_user(email="b@example.com", username=None)
    auth.set_role(other["id"], "admin")

    assert manage.main(["--db", str(db), "set-role", "solavolantes@gmail.com", "user"]) == 0

    assert "admin" not in capsys.readouterr().err.lower()


def test_list_users_prints_aligned_columns(db, auth, capsys):
    auth.create_user(email="solavolantes@gmail.com", username=None)
    auth.create_user(email="longer.address@example.com", username=None, status="suspended")

    assert manage.main(["--db", str(db), "list-users"]) == 0

    lines = capsys.readouterr().out.splitlines()
    assert lines[0].split() == ["EMAIL", "ROLE", "STATUS", "CREATED_AT"]
    rows = {line.split()[0]: line.split() for line in lines[1:]}
    assert rows["solavolantes@gmail.com"][1:3] == ["admin", "active"]
    assert rows["longer.address@example.com"][1:3] == ["user", "suspended"]
    role_column = lines[0].index("ROLE")
    assert all(line[role_column - 1] == " " for line in lines)
    assert all(line[role_column] != " " for line in lines)


def test_list_users_query_filters(db, auth, capsys):
    auth.create_user(email="alice@example.com", username=None)
    auth.create_user(email="bob@example.com", username=None)

    assert manage.main(["--db", str(db), "list-users", "--query", "alice"]) == 0

    out = capsys.readouterr().out
    assert "alice@example.com" in out
    assert "bob@example.com" not in out


def test_list_users_empty(db, auth, capsys):
    assert manage.main(["--db", str(db), "list-users"]) == 0

    assert "no users" in capsys.readouterr().out.lower()


def test_default_db_path_matches_api(monkeypatch, tmp_path):
    from backend import api

    assert api.DEFAULT_DB_PATH == db_path.DEFAULT_DB_PATH
    assert api._migrate_legacy_db_if_needed is db_path.migrate_legacy_db_if_needed

    monkeypatch.chdir(tmp_path)
    AuthStore(db_path.DEFAULT_DB_PATH).create_user(email="local@example.com", username=None)
    captured = {}

    def fake_run(args, path):
        captured["path"] = path
        return 0

    monkeypatch.setattr(manage, "run", fake_run)
    assert manage.main(["list-users"]) == 0
    assert captured["path"] == db_path.DEFAULT_DB_PATH


def test_default_db_path_migrates_legacy_db_like_api(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    AuthStore(db_path.LEGACY_DB_PATH).create_user(email="old@example.com", username=None)

    assert manage.main(["set-role", "old@example.com", "admin"]) == 0

    assert AuthStore(db_path.DEFAULT_DB_PATH).get_user_by_email("old@example.com")["role"] == "admin"


def test_module_entrypoint_runs_without_importing_api(db, auth):
    auth.create_user(email="a@example.com", username=None)
    script = (
        "import sys, runpy\n"
        "sys.argv = ['backend.manage', '--db', sys.argv[1], 'list-users']\n"
        "try:\n"
        "    runpy.run_module('backend.manage', run_name='__main__')\n"
        "finally:\n"
        "    assert 'backend.api' not in sys.modules\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script, str(db)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "a@example.com" in result.stdout
