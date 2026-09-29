#!/usr/bin/env bash
# Copy the backend SQLite database and organism profiles from the old
# docker-compose.backend.yml volumes into the volumes of docker-compose.prod.yml,
# so the new stack starts with every account, job, and profile.
#
# The source is never modified or deleted. By default it is mounted read-only,
# which needs the old backend stopped (a consistent copy; nothing written after
# it is lost). --online copies with SQLite's backup API while the old backend
# keeps running, for seeding staging; writes after the copy stay behind.
#
# Usage: deploy/scripts/migrate-to-prod-compose.sh [options]
#   --from-project NAME       old compose project                 (default: compose)
#   --to-project NAME         new compose project                 (default: gaa)
#   --from-backend SOURCE     old backend-data volume or absolute host dir (default: found by label)
#   --from-profiles SOURCE    old profiles-data volume or absolute host dir (default: found by label)
#   --image IMAGE             helper image with python3           (default: the prod backend image)
#   --online                  copy while the old backend is running (staging seed)
#   --force                   target not empty: move its files into .pre-migrate-<timestamp>/ first
#   --dry-run                 print what would happen, change nothing
set -euo pipefail

FROM_PROJECT=compose
TO_PROJECT=gaa
FROM_BACKEND=""
FROM_PROFILES=""
IMAGE="ghcr.io/cadsaltz/gene-autoannotator-backend:${IMAGE_TAG:-prod}"
ONLINE=0
FORCE=0
DRY_RUN=0

usage() {
  sed -n '11,19p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

die() {
  echo "error: $*" >&2
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --from-project) FROM_PROJECT="${2:?}"; shift 2 ;;
    --to-project) TO_PROJECT="${2:?}"; shift 2 ;;
    --from-backend) FROM_BACKEND="${2:?}"; shift 2 ;;
    --from-profiles) FROM_PROFILES="${2:?}"; shift 2 ;;
    --image) IMAGE="${2:?}"; shift 2 ;;
    --online) ONLINE=1; shift ;;
    --force) FORCE=1; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; die "unknown option: $1" ;;
  esac
done

command -v docker >/dev/null 2>&1 || die "docker is not installed"

volume_by_label() {
  local project="$1" volume="$2"
  docker volume ls -q \
    --filter "label=com.docker.compose.project=$project" \
    --filter "label=com.docker.compose.volume=$volume"
}

resolve_source() {
  local explicit="$1" volume="$2" found count
  if [[ -n "$explicit" ]]; then
    if [[ "$explicit" == /* ]]; then
      [[ -d "$explicit" ]] || die "source dir $explicit does not exist"
    else
      docker volume inspect "$explicit" >/dev/null 2>&1 || die "source volume $explicit does not exist"
    fi
    printf '%s' "$explicit"
    return
  fi
  found="$(volume_by_label "$FROM_PROJECT" "$volume")"
  count="$(printf '%s' "$found" | grep -c . || true)"
  if [[ "$count" != 1 ]]; then
    echo "error: expected one '$volume' volume for compose project '$FROM_PROJECT', found $count." >&2
    echo "Volumes named '$volume' by project:" >&2
    docker volume ls --filter "label=com.docker.compose.volume=$volume" \
      --format '  {{.Name}} (project {{.Label "com.docker.compose.project"}})' >&2
    die "pass --from-project, or --from-backend/--from-profiles"
  fi
  printf '%s' "$found"
}

SRC_BACKEND="$(resolve_source "$FROM_BACKEND" backend-data)"
SRC_PROFILES="$(resolve_source "$FROM_PROFILES" profiles-data)"
DST_BACKEND="${TO_PROJECT}_backend-data"
DST_PROFILES="${TO_PROJECT}_profiles-data"

for pair in "$SRC_BACKEND:$DST_BACKEND" "$SRC_PROFILES:$DST_PROFILES"; do
  [[ "${pair%%:*}" != "${pair#*:}" ]] || die "source and target are the same volume (${pair#*:})"
done

containers_using() {
  docker ps -q --filter "volume=$1"
}

if [[ "$SRC_BACKEND" != /* && "$ONLINE" != 1 && -n "$(containers_using "$SRC_BACKEND")" ]]; then
  die "a running container uses $SRC_BACKEND. Stop the old backend first
  (docker compose -f deploy/compose/docker-compose.backend.yml stop backend frontend),
  or pass --online to copy from the running backend (staging seed only)."
fi
for volume in "$DST_BACKEND" "$DST_PROFILES"; do
  if [[ -n "$(containers_using "$volume")" ]]; then
    die "a running container uses target $volume; stop the '$TO_PROJECT' stack first"
  fi
done

docker image inspect "$IMAGE" >/dev/null 2>&1 \
  || die "helper image $IMAGE is not available locally; docker pull it (or pass --image)"

echo "source backend:   $SRC_BACKEND"
echo "source profiles:  $SRC_PROFILES"
echo "target backend:   $DST_BACKEND"
echo "target profiles:  $DST_PROFILES"
echo "mode:             $([[ "$ONLINE" == 1 ]] && echo online || echo offline, source read-only)$([[ "$FORCE" == 1 ]] && echo ', force')"

if [[ "$DRY_RUN" == 1 ]]; then
  echo "dry run: nothing changed"
  exit 0
fi

# Compose adopts a pre-created volume without a warning when these labels match.
for pair in "backend-data:$DST_BACKEND" "profiles-data:$DST_PROFILES"; do
  name="${pair#*:}"
  if ! docker volume inspect "$name" >/dev/null 2>&1; then
    docker volume create \
      --label "com.docker.compose.project=$TO_PROJECT" \
      --label "com.docker.compose.volume=${pair%%:*}" \
      "$name" >/dev/null
    echo "created volume $name"
  fi
done

SRC_MODE=ro
[[ "$ONLINE" == 1 ]] && SRC_MODE=rw

read -r -d '' HELPER <<'PY' || true
import os
import shutil
import sqlite3
import sys

SRC, DST = "/src/backend", "/dst/backend"
SRC_PROFILES, DST_PROFILES = "/src/profiles", "/dst/profiles"
DB = "jobs.sqlite3"
SIDECARS = ("-wal", "-shm", "-journal")
ONLINE = os.environ["ONLINE"] == "1"
FORCE = os.environ["FORCE"] == "1"
STAMP = os.environ["STAMP"]
ASIDE = f".pre-migrate-{STAMP}"
APP_UID = APP_GID = 10001


def fail(message):
    print(f"error: {message}", file=sys.stderr)
    sys.exit(1)


def contents(path):
    return sorted(
        name for name in os.listdir(path)
        if name != "lost+found" and not name.startswith(".pre-migrate-")
    )


def set_aside(path, names):
    aside = os.path.join(path, ASIDE)
    os.mkdir(aside)
    for name in names:
        os.rename(os.path.join(path, name), os.path.join(aside, name))
    print(f"moved {len(names)} existing entr{'y' if len(names) == 1 else 'ies'} to {path}/{ASIDE}")


def copy_entry(src, dst):
    if os.path.isdir(src) and not os.path.islink(src):
        shutil.copytree(src, dst, symlinks=True)
    else:
        shutil.copy2(src, dst, follow_symlinks=False)


def chown_tree(path):
    os.lchown(path, APP_UID, APP_GID)
    for root, dirs, files in os.walk(path):
        for name in dirs + files:
            os.lchown(os.path.join(root, name), APP_UID, APP_GID)


def table_count(connection, table):
    exists = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ).fetchone()
    if not exists:
        return "n/a"
    return connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


if not os.path.isfile(os.path.join(SRC, DB)):
    fail(f"no {DB} in the source backend volume; wrong --from-project or --from-backend?")

existing = {DST: contents(DST), DST_PROFILES: contents(DST_PROFILES)}
if any(existing.values()) and not FORCE:
    for path, names in existing.items():
        if names:
            print(f"target {path} is not empty: {', '.join(names[:5])}", file=sys.stderr)
    fail("refusing to overwrite; re-run with --force to move the existing files aside")
for path, names in existing.items():
    if names:
        set_aside(path, names)

staging = os.path.join(DST, f".migrate-tmp-{STAMP}")
os.mkdir(staging)
try:
    if ONLINE:
        source = sqlite3.connect(os.path.join(SRC, DB), timeout=30)
    else:
        # The source is read-only, so SQLite cannot replay its WAL in place:
        # copy the file set first and let SQLite recover the copy.
        for suffix in ("",) + SIDECARS:
            path = os.path.join(SRC, DB + suffix)
            if os.path.exists(path):
                shutil.copy2(path, os.path.join(staging, DB + suffix))
        source = sqlite3.connect(os.path.join(staging, DB))
    staged_db = os.path.join(staging, "migrated.sqlite3")
    target = sqlite3.connect(staged_db)
    source.backup(target)
    source.close()
    target.execute("PRAGMA journal_mode=DELETE")
    check = target.execute("PRAGMA integrity_check").fetchone()[0]
    counts = {table: table_count(target, table) for table in ("users", "annotation_jobs", "annotation_batches")}
    target.close()
    if check != "ok":
        fail(f"integrity_check on the copy failed: {check}")
    os.replace(staged_db, os.path.join(DST, DB))
finally:
    shutil.rmtree(staging, ignore_errors=True)

skipped = {DB + suffix for suffix in ("",) + SIDECARS}
for name in contents(SRC):
    if name not in skipped and not name.startswith(".migrate-tmp-"):
        copy_entry(os.path.join(SRC, name), os.path.join(DST, name))
profiles = contents(SRC_PROFILES)
for name in profiles:
    copy_entry(os.path.join(SRC_PROFILES, name), os.path.join(DST_PROFILES, name))

chown_tree(DST)
chown_tree(DST_PROFILES)
print(
    "copied database (integrity ok; "
    + ", ".join(f"{table}={count}" for table, count in counts.items())
    + f") and {len(profiles)} profile entr{'y' if len(profiles) == 1 else 'ies'}"
)
PY

docker run --rm \
  --user 0:0 \
  --network none \
  --entrypoint python \
  -e ONLINE="$ONLINE" \
  -e FORCE="$FORCE" \
  -e STAMP="$(date -u +%Y%m%dT%H%M%SZ)" \
  -v "$SRC_BACKEND:/src/backend:$SRC_MODE" \
  -v "$SRC_PROFILES:/src/profiles:ro" \
  -v "$DST_BACKEND:/dst/backend" \
  -v "$DST_PROFILES:/dst/profiles" \
  "$IMAGE" -c "$HELPER"

echo "done. Start the new stack with: docker compose -p $TO_PROJECT -f deploy/compose/docker-compose.prod.yml --env-file <compose env file> up -d"
