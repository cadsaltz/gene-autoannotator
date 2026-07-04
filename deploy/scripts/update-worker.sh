#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"

ARG_URL="${1:-}"
DRAIN_TIMEOUT_SECONDS="${DRAIN_TIMEOUT_SECONDS:-300}"
POLL_INTERVAL="${POLL_INTERVAL:-5}"

load_worker_env() {
  for env_file in worker.env /etc/gene-autoannotator/worker.env; do
    if [[ -f "$env_file" ]]; then
      # shellcheck disable=SC1090
      set -a
      # shellcheck disable=SC1090
      source "$env_file"
      set +a
      return 0
    fi
  done
  return 1
}

if [[ -n "$ARG_URL" ]]; then
  COORDINATOR_URL="$ARG_URL"
elif ! load_worker_env; then
  echo "Error: pass COORDINATOR_URL or create worker.env" >&2
  exit 1
fi

if [[ -z "${COORDINATOR_URL:-}" ]]; then
  echo "Error: COORDINATOR_URL is not set" >&2
  exit 1
fi

BASE="${COORDINATOR_URL%/}"
HOST="$(hostname)"
WORKER_LABEL="${WORKER_NAME:-$HOST}"
export HOST WORKER_LABEL

find_worker() {
  curl -sf "${BASE}/workers"
}

request_drain() {
  local worker_id="$1"
  local auth_args=()
  if [[ -n "${WORKER_API_TOKEN:-}" ]]; then
    auth_args=(-H "Authorization: Bearer ${WORKER_API_TOKEN}")
  fi
  curl -sf -X POST "${auth_args[@]}" "${BASE}/workers/${worker_id}/drain" >/dev/null || true
}

worker_info="$(find_worker | python3 -c "
import json, os, sys
hostname = os.environ['HOST']
label = os.environ['WORKER_LABEL']
data = json.load(sys.stdin)
for w in data.get('workers', []):
    if w.get('hostname') == hostname or w.get('worker_name') in (hostname, label):
        print(w['id'])
        print(w.get('active_jobs', 0))
        sys.exit(0)
print('', file=sys.stderr)
sys.exit(1)
" 2>/dev/null)" || {
  echo "Warning: this host ($HOST) is not registered with the coordinator; skipping drain wait."
  worker_info=""
}

if [[ -n "$worker_info" ]]; then
  worker_id="$(sed -n '1p' <<<"$worker_info")"
  active_jobs="$(sed -n '2p' <<<"$worker_info")"
  echo "Found worker $worker_id ($WORKER_LABEL) with active_jobs=$active_jobs"

  if [[ "$active_jobs" != "0" ]]; then
    echo "Requesting drain on worker $worker_id ..."
    request_drain "$worker_id"

    deadline=$((SECONDS + DRAIN_TIMEOUT_SECONDS))
    while [[ "$SECONDS" -lt "$deadline" ]]; do
      export WORKER_ID="$worker_id"
      active_jobs="$(find_worker | python3 -c "
import json, os, sys
worker_id = os.environ['WORKER_ID']
data = json.load(sys.stdin)
for w in data.get('workers', []):
    if w['id'] == worker_id:
        print(w.get('active_jobs', 0))
        sys.exit(0)
print('0')
")"
      if [[ "$active_jobs" == "0" ]]; then
        echo "Worker drained (active_jobs=0)."
        break
      fi
      echo "Waiting for active jobs to finish ($active_jobs remaining) ..."
      sleep "$POLL_INTERVAL"
    done

    if [[ "$active_jobs" != "0" ]]; then
      echo "Warning: timed out after ${DRAIN_TIMEOUT_SECONDS}s with active_jobs=$active_jobs; continuing anyway." >&2
    fi
  else
    echo "No active jobs; safe to update."
  fi
fi

echo "Pulling latest code ..."
git pull

if systemctl list-unit-files gene-autoannotator-worker.service >/dev/null 2>&1 \
  && systemctl is-enabled gene-autoannotator-worker >/dev/null 2>&1; then
  echo "Restarting gene-autoannotator-worker via systemd ..."
  sudo systemctl restart gene-autoannotator-worker
  sudo systemctl status gene-autoannotator-worker --no-pager || true
else
  cat <<EOF

systemd unit not enabled. Restart the worker manually:

  cd $REPO_ROOT
  source .venv/bin/activate
  python -m worker

EOF
fi

echo "Update complete."
