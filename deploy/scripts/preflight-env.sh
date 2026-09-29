#!/usr/bin/env bash
# Check that an env file sets every variable the containers need at runtime.
# Prints only `OK NAME`, `MISSING NAME`, `PLACEHOLDER NAME` (still CHANGE_ME), or
# `INVALID NAME (...)`, never values. Exit 1 if any check fails, 2 if the file
# does not exist.
#
# Usage: deploy/scripts/preflight-env.sh [--role ROLE] [ENV_FILE]
#   --role combined  (default) shared .env for docker-compose.backend.yml; default <repo>/.env
#   --role backend   backend.env for docker-compose.prod.yml; default deploy/compose/backend.env
#   --role frontend  frontend.env for docker-compose.prod.yml; default deploy/compose/frontend.env
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ROLE=combined

usage() {
  sed -n '7,10p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//' >&2
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --role)
      [[ $# -ge 2 ]] || { usage; exit 2; }
      ROLE="$2"
      shift 2
      ;;
    --role=*)
      ROLE="${1#--role=}"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      break
      ;;
  esac
done

case "$ROLE" in
  combined) DEFAULT_FILE="$REPO_ROOT/.env" ;;
  backend) DEFAULT_FILE="$REPO_ROOT/deploy/compose/backend.env" ;;
  frontend) DEFAULT_FILE="$REPO_ROOT/deploy/compose/frontend.env" ;;
  *)
    echo "unknown role: $ROLE (expected combined, backend, or frontend)" >&2
    exit 2
    ;;
esac

ENV_FILE="${1:-$DEFAULT_FILE}"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "MISSING env file: $ENV_FILE" >&2
  exit 2
fi

declare -A VALUES=()

# The file is parsed, never sourced, so nothing in it is executed.
while IFS= read -r line || [[ -n "$line" ]]; do
  line="${line%$'\r'}"
  line="${line#"${line%%[![:space:]]*}"}"
  [[ -z "$line" || "$line" == \#* ]] && continue
  line="${line#export }"
  [[ "$line" == *=* ]] || continue
  key="${line%%=*}"
  key="${key%"${key##*[![:space:]]}"}"
  value="${line#*=}"
  value="${value#"${value%%[![:space:]]*}"}"
  if [[ "$value" == \"*\" || "$value" == \'*\' ]]; then
    value="${value:1:${#value}-2}"
  else
    value="${value%% #*}"
  fi
  value="${value%"${value##*[![:space:]]}"}"
  VALUES["$key"]="$value"
done < "$ENV_FILE"

missing=0

value_of() {
  printf '%s' "${VALUES[$1]:-}"
}

# check NAME [ALIAS...]: the first alias with a value counts.
check() {
  local name="$1"
  shift
  local alias value
  for alias in "$name" "$@"; do
    value="$(value_of "$alias")"
    if [[ -n "$value" ]]; then
      if [[ "$value" == *CHANGE_ME* ]]; then
        echo "PLACEHOLDER $name"
        missing=1
      else
        echo "OK $name"
      fi
      return
    fi
  done
  echo "MISSING $name"
  missing=1
}

check_enabled() {
  local name="$1"
  local value
  value="$(value_of "$name" | tr '[:upper:]' '[:lower:]')"
  if [[ -z "$value" ]]; then
    echo "MISSING $name"
    missing=1
  elif [[ "$value" == 1 || "$value" == true || "$value" == yes ]]; then
    echo "OK $name"
  else
    echo "INVALID $name (must be 1 behind Caddy)"
    missing=1
  fi
}

check_email() {
  check EMAIL_BACKEND
  if [[ "$(value_of EMAIL_BACKEND | tr '[:upper:]' '[:lower:]')" == "resend" ]]; then
    check RESEND_API_KEY
    check EMAIL_FROM
  fi
}

case "$ROLE" in
  combined)
    # Backend annotation history + backups, and the frontend's /api/annotations routes.
    check MONGO_URI MONGODB_URI
    check WORKER_API_TOKEN
    check REQUIRE_WORKER_API_TOKEN
    check SESSION_COOKIE_SECURE
    check_email
    ;;
  backend)
    check MONGO_URI MONGODB_URI
    check WORKER_API_TOKEN
    check_enabled REQUIRE_WORKER_API_TOKEN
    check SESSION_COOKIE_SECURE
    check_enabled TRUST_FORWARDED_FOR
    check_email
    ;;
  frontend)
    check MONGO_URI MONGODB_URI
    check BACKEND_API_BASE_URL
    ;;
esac

exit "$missing"
