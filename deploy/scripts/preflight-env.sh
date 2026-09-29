#!/usr/bin/env bash
# Check that the compose env file sets every variable the backend and frontend
# containers need at runtime. Prints only `OK NAME` / `MISSING NAME`, never values.
# Usage: deploy/scripts/preflight-env.sh [ENV_FILE]   (default: <repo>/.env)
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="${1:-$REPO_ROOT/.env}"

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

check() {
  local name="$1"
  shift
  local alias
  for alias in "$name" "$@"; do
    if [[ -n "$(value_of "$alias")" ]]; then
      echo "OK $name"
      return
    fi
  done
  echo "MISSING $name"
  missing=1
}

# Backend annotation history + backups, and the frontend's /api/annotations routes.
check MONGO_URI MONGODB_URI
check WORKER_API_TOKEN
check REQUIRE_WORKER_API_TOKEN
check SESSION_COOKIE_SECURE
check EMAIL_BACKEND
if [[ "$(value_of EMAIL_BACKEND | tr '[:upper:]' '[:lower:]')" == "resend" ]]; then
  check RESEND_API_KEY
  check EMAIL_FROM
fi

exit "$missing"
