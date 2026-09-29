"""Operator CLI for accounts and backups: ``python -m backend.manage <command>``.

This is the lockout-recovery path, so unlike the admin API it has no
last-admin guard; it only warns when a change leaves no active admins.
"""

import argparse
import os
import sys
from pathlib import Path

from . import backup
from .access import ROLES, STATUSES
from .audit_store import AuditStore
from .auth_store import AuthStore
from .db_path import DEFAULT_DB_PATH, migrate_legacy_db_if_needed
from .job_store import JobStore
from .profile_store import DEFAULT_PROFILES_DIR

EXIT_OK = 0
EXIT_ERROR = 1
BACKUP_COMMANDS = ("backup", "list-backups", "restore")
RESTORE_WARNING = (
    "warning: stop the backend before restoring (docker compose stop backend); "
    "a running backend keeps using the old database and can overwrite the restore"
)


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
        description=(
            "Manage backend user accounts (roles, status, sessions, jobs) and "
            "control-plane backups."
        ),
    )
    parser.add_argument(
        "--db",
        type=Path,
        help=f"SQLite database path (default: {DEFAULT_DB_PATH}, same as the API)",
    )
    parser.add_argument(
        "--profiles-dir",
        type=Path,
        help=(
            "Profiles directory for backup/restore "
            f"(default: $PROFILES_DIR or {DEFAULT_PROFILES_DIR}, same as the API)"
        ),
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
        "set-status",
        help="Change a user's status (suspending also revokes sessions and cancels jobs)",
    )
    set_status.add_argument("email")
    set_status.add_argument("value", metavar="{" + ",".join(STATUSES) + "}")

    revoke = commands.add_parser("revoke-sessions", help="Sign a user out everywhere")
    revoke.add_argument("email")

    cancel = commands.add_parser("cancel-jobs", help="Cancel a user's queued and running jobs")
    cancel.add_argument("email")

    commands.add_parser(
        "backup", help="Upload a snapshot of the database and profiles to MongoDB"
    )
    commands.add_parser("list-backups", help="List snapshots stored in MongoDB, newest first")
    restore = commands.add_parser(
        "restore",
        help="Restore a snapshot (stop the backend first)",
        description=(
            "Restore the database and profiles from a MongoDB snapshot. Without "
            "--force it refuses when the database or profile files already exist; "
            "with --force it moves them aside to *.pre-restore-<timestamp>."
        ),
    )
    restore.add_argument(
        "--id", default="latest", help="Snapshot id from list-backups (default: latest)"
    )
    restore.add_argument(
        "--force", action="store_true", help="Move the existing database and profiles aside"
    )
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


def _set_status(auth: AuthStore, audit: AuditStore, jobs: JobStore, args) -> None:
    status = _require_choice(args.value, STATUSES, "status")
    user = _require_user(auth, args.email)
    if user["status"] == status:
        print(f"{user['email']}: status is already {status}")
        return
    auth.set_status(user["id"], status)
    details = {"from": user["status"], "to": status}
    try:
        if status == "suspended":
            details["cancelled_jobs"] = None
            details["cancelled_jobs"] = jobs.cancel_active_for_user(user["id"], by="cli")
    finally:
        _audit(audit, "status_change", user, details)
    print(f"{user['email']}: status {user['status']} -> {status}")
    if status == "suspended":
        print(f"{user['email']}: cancelled {details['cancelled_jobs']} job(s)")
        revoked = auth.revoke_sessions(user["id"])
        _audit(audit, "sessions_revoked", user, {"count": revoked})
        print(f"{user['email']}: revoked {revoked} session(s)")
    _warn_if_no_admins(auth)


def _revoke_sessions(auth: AuthStore, audit: AuditStore, args) -> None:
    user = _require_user(auth, args.email)
    revoked = auth.revoke_sessions(user["id"])
    _audit(audit, "sessions_revoked", user, {"count": revoked})
    print(f"{user['email']}: revoked {revoked} session(s)")


def _cancel_jobs(auth: AuthStore, audit: AuditStore, jobs: JobStore, args) -> None:
    user = _require_user(auth, args.email)
    cancelled = jobs.cancel_active_for_user(user["id"], by="cli")
    _audit(audit, "jobs_cancelled", user, {"cancelled_jobs": cancelled})
    print(f"{user['email']}: cancelled {cancelled} job(s)")


def _backup(db_path: Path, profiles_dir: Path, keep: int) -> None:
    result = backup.run_backup(db_path=db_path, profiles_dir=profiles_dir, keep=keep)
    AuditStore(db_path).record(
        action="backup_created",
        actor_user_id=None,
        target_type="backup",
        target_id=result["id"],
        details={"bytes": result["size"], "source": "cli"},
    )
    print(f"Uploaded backup {result['id']} ({result['size']} bytes)")


def _list_backups() -> None:
    with backup.mongo_database_from_env() as mongo_db:
        snapshots = backup.list_snapshots(mongo_db)
    if not snapshots:
        print("No backups.")
        return
    rows = [("ID", "CREATED_AT", "SIZE")] + [
        (item["id"], item["created_at"], str(item["size"])) for item in snapshots
    ]
    widths = [max(len(row[i]) for row in rows) for i in range(2)]
    for row in rows:
        print("  ".join([*(cell.ljust(w) for cell, w in zip(row, widths)), row[-1]]))


def _restore(db_path: Path, profiles_dir: Path, args) -> None:
    print(RESTORE_WARNING, file=sys.stderr)
    with backup.mongo_database_from_env() as mongo_db:
        result = backup.restore_snapshot(
            mongo_db, args.id, db_path=db_path, profiles_dir=profiles_dir, force=args.force
        )
    AuditStore(db_path).record(
        action="backup_restored",
        actor_user_id=None,
        target_type="backup",
        target_id=result["id"],
        details={"created_at": result["created_at"], "source": "cli"},
    )
    print(
        f"Restored backup {result['id']} (created {result['created_at']}) into {db_path} "
        f"and {result['profiles']} profile file(s) into {profiles_dir}"
    )
    for path in result["moved_aside"]:
        print(f"Moved aside: {path}")


def run_backup_command(args, db_path: Path) -> int:
    from pymongo.errors import PyMongoError

    profiles_dir = args.profiles_dir or Path(os.getenv("PROFILES_DIR") or DEFAULT_PROFILES_DIR)
    try:
        if args.command == "backup":
            if not Path(db_path).is_file():
                raise CommandError(f"database not found: {db_path}")
            _backup(db_path, profiles_dir, backup.BackupConfig.from_env().keep)
        elif args.command == "list-backups":
            _list_backups()
        elif args.command == "restore":
            _restore(db_path, profiles_dir, args)
    except (CommandError, backup.BackupError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    except PyMongoError as exc:
        print(f"error: MongoDB request failed: {exc}", file=sys.stderr)
        return EXIT_ERROR
    return EXIT_OK


def run(args, db_path: Path) -> int:
    auth = AuthStore(db_path)
    audit = AuditStore(db_path)
    jobs = JobStore(db_path)
    try:
        if args.command == "list-users":
            _list_users(auth, args)
        elif args.command == "set-role":
            _set_role(auth, audit, args)
        elif args.command == "set-status":
            _set_status(auth, audit, jobs, args)
        elif args.command == "revoke-sessions":
            _revoke_sessions(auth, audit, args)
        elif args.command == "cancel-jobs":
            _cancel_jobs(auth, audit, jobs, args)
    except CommandError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command in BACKUP_COMMANDS:
        # Not migrate_legacy_db_if_needed: a restore target must stay absent.
        return run_backup_command(args, args.db if args.db is not None else DEFAULT_DB_PATH)
    db_path = args.db if args.db is not None else migrate_legacy_db_if_needed(DEFAULT_DB_PATH)
    # The stores create missing files; refuse so a wrong cwd or --db can't
    # silently operate on a fresh empty database.
    if not Path(db_path).is_file():
        print(f"error: database not found: {db_path}", file=sys.stderr)
        return EXIT_ERROR
    return run(args, db_path)


if __name__ == "__main__":
    raise SystemExit(main())
