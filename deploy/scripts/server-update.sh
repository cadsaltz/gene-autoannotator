#!/usr/bin/env bash
# Pull new images for the production stack and recreate only what changed.
# Meant for cron every 5 minutes, e.g. in root's crontab:
#   */5 * * * * /opt/gaa/repo/deploy/scripts/server-update.sh
# Does nothing unless the project's backend is already running, so it never
# starts a stack that was stopped on purpose (before cutover, after a rollback).
# A run that finds nothing new logs one line. Overlapping runs exit at once.
#
# Environment (all optional):
#   GAA_PROJECT          compose project name (default: gaa)
#   GAA_COMPOSE_FILES    colon-separated compose files, one -f each; include every
#                        override the stack was started with, e.g.
#                        .../docker-compose.prod.yml:.../docker-compose.worker-port.yml
#   GAA_COMPOSE_FILE     single compose file, used when GAA_COMPOSE_FILES is unset
#                        (default: <repo>/deploy/compose/docker-compose.prod.yml)
#   GAA_ENV_FILE         --env-file (default: compose.env beside the first compose file)
#   GAA_UPDATE_LOG       log file (default: /var/log/gaa-update.log)
#   GAA_UPDATE_LOCK      lock file (default: /run/lock/gaa-update.lock, else /tmp/gaa-update.lock)
#   GAA_HEALTH_TIMEOUT   seconds to wait for /healthz after an update (default: 90)
#   GAA_IMAGE_PREFIX     image repo prefix for :previous tags (default: ghcr.io/cadsaltz/gene-autoannotator)
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

PROJECT="${GAA_PROJECT:-gaa}"
IFS=: read -r -a COMPOSE_FILES <<<"${GAA_COMPOSE_FILES:-${GAA_COMPOSE_FILE:-$REPO_ROOT/deploy/compose/docker-compose.prod.yml}}"
COMPOSE_DIR="$(cd "$(dirname "${COMPOSE_FILES[0]}")" && pwd)"
ENV_FILE="${GAA_ENV_FILE:-$COMPOSE_DIR/compose.env}"
LOG_FILE="${GAA_UPDATE_LOG:-/var/log/gaa-update.log}"
if [[ -n "${GAA_UPDATE_LOCK:-}" ]]; then
  LOCK_FILE="$GAA_UPDATE_LOCK"
elif [[ -d /run/lock && -w /run/lock ]]; then
  LOCK_FILE=/run/lock/gaa-update.lock
else
  LOCK_FILE=/tmp/gaa-update.lock
fi
HEALTH_TIMEOUT="${GAA_HEALTH_TIMEOUT:-90}"
HEALTH_INTERVAL="${GAA_HEALTH_INTERVAL:-5}"
IMAGE_PREFIX="${GAA_IMAGE_PREFIX:-ghcr.io/cadsaltz/gene-autoannotator}"
SERVICES=(backend frontend caddy)

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

COMPOSE_ARGS=(-p "$PROJECT")
for file in "${COMPOSE_FILES[@]}"; do
  COMPOSE_ARGS+=(-f "$file")
done
COMPOSE_ARGS+=(--env-file "$ENV_FILE")

compose() {
  docker compose "${COMPOSE_ARGS[@]}" "$@"
}

# env_file names come from the compose env file; relative ones sit beside the
# first compose file, as compose resolves them.
env_path() {
  local key="$1" default="$2" value
  value="$(sed -n "s/^[[:space:]]*${key}=//p" "$ENV_FILE" | tail -n 1 | tr -d '\r"'"'")"
  value="${value:-$default}"
  if [[ "$value" == /* ]]; then
    printf '%s' "$value"
  else
    printf '%s' "$COMPOSE_DIR/$value"
  fi
}

running_images() {
  local service cid
  for service in "${SERVICES[@]}"; do
    cid="$(compose ps -q "$service" 2>/dev/null | head -n 1)"
    if [[ -n "$cid" ]]; then
      printf '%s=%s\n' "$service" "$(docker inspect -f '{{.Image}}' "$cid")"
    else
      printf '%s=\n' "$service"
    fi
  done
}

backend_healthy() {
  compose exec -T backend python -c \
    "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3)" \
    >/dev/null 2>&1
}

trap 'log "update FAILED (exit $?)"' ERR

for path in "${COMPOSE_FILES[@]}" "$ENV_FILE"; do
  if [[ ! -f "$path" ]]; then
    log "missing $path; nothing done"
    exit 1
  fi
done

if [[ -z "$(compose ps -q --status running backend 2>/dev/null)" ]]; then
  log "stack not running; skipping"
  exit 0
fi

PREFLIGHT="$SCRIPT_DIR/preflight-env.sh"
if [[ -x "$PREFLIGHT" ]]; then
  preflight_ok=1
  backend_out="$("$PREFLIGHT" --role backend "$(env_path BACKEND_ENV_FILE backend.env)" 2>&1)" || preflight_ok=0
  frontend_out="$("$PREFLIGHT" --role frontend "$(env_path FRONTEND_ENV_FILE frontend.env)" 2>&1)" || preflight_ok=0
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

before="$(running_images)"
compose pull --quiet
compose up -d --quiet-pull
after="$(running_images)"

if [[ "$before" == "$after" ]]; then
  log "no new images"
  exit 0
fi

log "updated:"
while IFS='=' read -r service old_image; do
  new_image="$(printf '%s\n' "$after" | sed -n "s/^${service}=//p")"
  if [[ "$old_image" != "$new_image" ]]; then
    echo "  $service: ${old_image:-none} -> ${new_image:-none}"
  fi
  # Both app images get :previous, changed or not, so IMAGE_TAG=previous
  # restores exactly the pair that ran before; it also keeps a replaced image
  # out of the dangling prune below.
  if [[ -n "$old_image" && "$service" != caddy ]]; then
    docker tag "$old_image" "$IMAGE_PREFIX-$service:previous"
  fi
done <<<"$before"
echo "  pre-update backend/frontend images tagged :previous"

deadline=$((SECONDS + HEALTH_TIMEOUT))
until backend_healthy; do
  if (( SECONDS >= deadline )); then
    trap - ERR
    log "ERROR: backend is not healthy ${HEALTH_TIMEOUT}s after the update."
    log "ERROR: images before: $(printf '%s ' $before)"
    log "ERROR: to roll back: disable this cron job, set IMAGE_TAG=previous in $ENV_FILE, run docker compose ${COMPOSE_ARGS[*]} up -d (see deploy/README.md)"
    compose ps --format 'table {{.Service}}\t{{.Status}}' || true
    exit 1
  fi
  sleep "$HEALTH_INTERVAL"
done
log "backend healthy"

compose ps --format 'table {{.Service}}\t{{.Status}}'
# Without -a only dangling (untagged) images go; :previous stays.
docker image prune -f
log "update done"
