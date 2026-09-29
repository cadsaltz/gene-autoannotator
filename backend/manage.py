"""Operator CLI for accounts: ``python -m backend.manage <command>``.

This is the lockout-recovery path, so unlike the admin API it has no
last-admin guard; it only warns when a change leaves no active admins.
"""

import argparse
import sys
from pathlib import Path

from .access import ROLES, STATUSES
from .audit_store import AuditStore
from .auth_store import AuthStore
from .db_path import DEFAULT_DB_PATH, migrate_legacy_db_if_needed

EXIT_OK = 0
EXIT_ERROR = 1


class CommandError(Exception):
    pass


def _positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return number


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m backend.manage",
        description="Manage backend user accounts (roles, status, sessions).",
    )
    parser.add_argument(
        "--db",
        type=Path,
        help=f"SQLite database path (default: {DEFAULT_DB_PATH}, same as the API)",
    )
    commands = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    list_users = commands.add_parser("list-users", help="List users")
    list_users.add_argument("--query", help="Filter by email or username substring")
    list_users.add_argument(
        "--limit", type=_positive_int, default=200, help="Maximum rows to show (default: 200)"
    )

    set_role = commands.add_parser("set-role", help="Change a user's role")
    set_role.add_argument("email")
    set_role.add_argument("value", metavar="{" + ",".join(ROLES) + "}")

    set_status = commands.add_parser(
        "set-status", help="Change a user's status (suspending also revokes sessions)"
    )
    set_status.add_argument("email")
    set_status.add_argument("value", metavar="{" + ",".join(STATUSES) + "}")

    revoke = commands.add_parser("revoke-sessions", help="Sign a user out everywhere")
    revoke.add_argument("email")
    return parser


def _require_user(auth: AuthStore, email: str) -> dict:
    user = auth.get_user_by_email(email)
    if user is None:
        raise CommandError(f"no user with email {email.strip()!r}")
    return user


def _require_choice(value: str, choices: tuple[str, ...], kind: str) -> str:
    if value not in choices:
        raise CommandError(f"invalid {kind} {value!r}; choose from: {', '.join(choices)}")
    return value


def _audit(audit: AuditStore, action: str, user: dict, details: dict) -> None:
    audit.record(
        action=action,
        actor_user_id=None,
        target_type="user",
        target_id=user["id"],
        ip=None,
        details={**details, "source": "cli"},
    )


def _warn_if_no_admins(auth: AuthStore) -> None:
    if auth.count_admins() == 0:
        print(
            "warning: there are now no active admins; restore access with "
            "`set-role EMAIL admin` and, if that user is suspended, `set-status EMAIL active`",
            file=sys.stderr,
        )


def _list_users(auth: AuthStore, args) -> None:
    users = auth.list_users(query=args.query, limit=args.limit)
    if not users:
        print("No users.")
        return
    header = ("EMAIL", "ROLE", "STATUS", "CREATED_AT")
    rows = [header] + [(u["email"], u["role"], u["status"], u["created_at"]) for u in users]
    widths = [max(len(row[i]) for row in rows) for i in range(len(header) - 1)]
    for row in rows:
        print("  ".join([*(cell.ljust(w) for cell, w in zip(row, widths)), row[-1]]))
    if len(users) == args.limit:
        print(
            f"note: showing the first {args.limit} users; there may be more "
            "(use --limit or --query)",
            file=sys.stderr,
        )


def _set_role(auth: AuthStore, audit: AuditStore, args) -> None:
    role = _require_choice(args.value, ROLES, "role")
    user = _require_user(auth, args.email)
    if user["role"] == role:
        print(f"{user['email']}: role is already {role}")
        return
    auth.set_role(user["id"], role)
    _audit(audit, "role_change", user, {"from": user["role"], "to": role})
    print(f"{user['email']}: role {user['role']} -> {role}")
    _warn_if_no_admins(auth)


def _set_status(auth: AuthStore, audit: AuditStore, args) -> None:
    status = _require_choice(args.value, STATUSES, "status")
    user = _require_user(auth, args.email)
    if user["status"] == status:
        print(f"{user['email']}: status is already {status}")
        return
    auth.set_status(user["id"], status)
    _audit(audit, "status_change", user, {"from": user["status"], "to": status})
    print(f"{user['email']}: status {user['status']} -> {status}")
    if status == "suspended":
        revoked = auth.revoke_sessions(user["id"])
        _audit(audit, "sessions_revoked", user, {"count": revoked})
        print(f"{user['email']}: revoked {revoked} session(s)")
    _warn_if_no_admins(auth)


def _revoke_sessions(auth: AuthStore, audit: AuditStore, args) -> None:
    user = _require_user(auth, args.email)
    revoked = auth.revoke_sessions(user["id"])
    _audit(audit, "sessions_revoked", user, {"count": revoked})
    print(f"{user['email']}: revoked {revoked} session(s)")


def run(args, db_path: Path) -> int:
    auth = AuthStore(db_path)
    audit = AuditStore(db_path)
    try:
        if args.command == "list-users":
            _list_users(auth, args)
        elif args.command == "set-role":
            _set_role(auth, audit, args)
        elif args.command == "set-status":
            _set_status(auth, audit, args)
        elif args.command == "revoke-sessions":
            _revoke_sessions(auth, audit, args)
    except CommandError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    db_path = args.db if args.db is not None else migrate_legacy_db_if_needed(DEFAULT_DB_PATH)
    # The stores create missing files; refuse so a wrong cwd or --db can't
    # silently operate on a fresh empty database.
    if not Path(db_path).is_file():
        print(f"error: database not found: {db_path}", file=sys.stderr)
        return EXIT_ERROR
    return run(args, db_path)


if __name__ == "__main__":
    raise SystemExit(main())
