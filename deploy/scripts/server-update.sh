#!/usr/bin/env bash
# Pull new images for the production stack and recreate only what changed.
# Meant for cron every 5 minutes, e.g. in root's crontab:
#   */5 * * * * /opt/gaa/repo/deploy/scripts/server-update.sh
# A run that finds nothing new logs one line. Overlapping runs exit at once.
#
# Environment (all optional):
#   GAA_PROJECT       compose project name                 (default: gaa)
#   GAA_COMPOSE_FILE  compose file                         (default: <repo>/deploy/compose/docker-compose.prod.yml)
#   GAA_ENV_FILE      --env-file with IMAGE_TAG, SITE_ADDRESS, ... (default: compose.env beside the compose file)
#   GAA_UPDATE_LOG    log file                             (default: /var/log/gaa-update.log)
#   GAA_UPDATE_LOCK   lock file                            (default: /tmp/gaa-update.lock)
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

PROJECT="${GAA_PROJECT:-gaa}"
COMPOSE_FILE="${GAA_COMPOSE_FILE:-$REPO_ROOT/deploy/compose/docker-compose.prod.yml}"
COMPOSE_DIR="$(cd "$(dirname "$COMPOSE_FILE")" && pwd)"
ENV_FILE="${GAA_ENV_FILE:-$COMPOSE_DIR/compose.env}"
LOG_FILE="${GAA_UPDATE_LOG:-/var/log/gaa-update.log}"
LOCK_FILE="${GAA_UPDATE_LOCK:-/tmp/gaa-update.lock}"

# cron runs with a minimal PATH; docker may live in /usr/local/bin or /snap/bin.
export PATH="$PATH:/usr/local/bin:/usr/bin:/bin:/snap/bin"

exec >>"$LOG_FILE" 2>&1

log() {
  printf '%s [%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$PROJECT" "$*"
}

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  log "another update is running; skipping"
  exit 0
fi

compose() {
  docker compose -p "$PROJECT" -f "$COMPOSE_FILE" --env-file "$ENV_FILE" "$@"
}

# env_file names come from the compose env file; default to the prod names.
env_value() {
  local key="$1" default="$2" value
  value="$(sed -n "s/^[[:space:]]*${key}=//p" "$ENV_FILE" | tail -n 1 | tr -d '\r"'"'")"
  printf '%s' "${value:-$default}"
}

trap 'log "update FAILED (exit $?)"' ERR

for path in "$COMPOSE_FILE" "$ENV_FILE"; do
  if [[ ! -f "$path" ]]; then
    log "missing $path; nothing done"
    exit 1
  fi
done

PREFLIGHT="$SCRIPT_DIR/preflight-env.sh"
if [[ -x "$PREFLIGHT" ]]; then
  backend_env="$COMPOSE_DIR/$(env_value BACKEND_ENV_FILE backend.env)"
  frontend_env="$COMPOSE_DIR/$(env_value FRONTEND_ENV_FILE frontend.env)"
  preflight_ok=1
  backend_out="$("$PREFLIGHT" --role backend "$backend_env" 2>&1)" || preflight_ok=0
  frontend_out="$("$PREFLIGHT" --role frontend "$frontend_env" 2>&1)" || preflight_ok=0
  if [[ "$preflight_ok" != 1 ]]; then
    log "preflight failed; running stack left as is:"
    {
      printf '%s\n' "$backend_out" | sed 's/^/backend: /'
      printf '%s\n' "$frontend_out" | sed 's/^/frontend: /'
    } | grep -v ': OK ' || true
    exit 1
  fi
else
  log "preflight-env.sh not found beside this script; skipping env check"
fi

running_before="$(compose images --quiet 2>/dev/null | sort | tr '\n' ' ')"

compose pull --quiet
compose up -d --quiet-pull

running_after="$(compose images --quiet 2>/dev/null | sort | tr '\n' ' ')"

if [[ "$running_before" == "$running_after" ]]; then
  log "no new images"
  exit 0
fi

log "updated; running images now: $running_after"
compose ps --format 'table {{.Service}}\t{{.Status}}'
# Without -a only dangling (untagged) images go; tagged rollback images stay.
docker image prune -f
log "update done"
