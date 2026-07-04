#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"

usage() {
  cat <<EOF
Usage: $0 [COORDINATOR_URL] [WORKER_API_TOKEN] [ANNOTATION_MEMORY_BUDGET_GB]

Install the worker agent in this repo clone (dev/lab). Creates .venv, installs
dependencies, and writes worker.env when URL and token are provided.

If worker.env already exists, bootstrap runs non-interactively using saved values
(optional args override).

Without worker.env or args, run once interactively:
  python -m worker
EOF
}

if [[ ! -f worker/__main__.py ]]; then
  echo "Error: run this script from the repository root (worker/__main__.py not found)." >&2
  exit 1
fi

COORDINATOR_URL="${1:-}"
WORKER_API_TOKEN="${2:-}"
MEMORY_GB="${3:-}"

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "Error: python3 is required." >&2
  exit 1
fi

if [[ ! -d .venv ]]; then
  echo "Creating virtualenv in .venv ..."
  python3 -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -r requirements.txt -r requirements-web.txt

run_bootstrap() {
  export INSTALL_COORDINATOR_URL="${COORDINATOR_URL:-}"
  export INSTALL_WORKER_TOKEN="${WORKER_API_TOKEN:-}"
  export INSTALL_MEMORY_GB="${MEMORY_GB:-}"
  python <<'PY'
import os
from worker.bootstrap import ensure_worker_env

overrides = {}
if os.environ.get("INSTALL_COORDINATOR_URL"):
    overrides["COORDINATOR_URL"] = os.environ["INSTALL_COORDINATOR_URL"]
if os.environ.get("INSTALL_WORKER_TOKEN"):
    overrides["WORKER_API_TOKEN"] = os.environ["INSTALL_WORKER_TOKEN"]
if os.environ.get("INSTALL_MEMORY_GB"):
    overrides["ANNOTATION_MEMORY_BUDGET_GB"] = float(os.environ["INSTALL_MEMORY_GB"])
ensure_worker_env(cli_overrides=overrides or None)
print("Wrote/updated worker.env")
PY
}

if [[ -f worker.env ]]; then
  echo "Found worker.env — running bootstrap non-interactively ..."
  run_bootstrap
elif [[ -n "$COORDINATOR_URL" && -n "$WORKER_API_TOKEN" ]]; then
  echo "Creating worker.env from script arguments ..."
  run_bootstrap
else
  cat <<EOF

No worker.env found and COORDINATOR_URL / WORKER_API_TOKEN were not provided.

Option A — interactive first run (prompts for URL, token, memory budget):
  source .venv/bin/activate
  python -m worker

Option B — pass credentials to this script:
  $0 http://coordinator-host:8000 <token> [memory_gb]

Generate a token on the coordinator host:
  deploy/scripts/generate-worker-token.sh

EOF
  exit 1
fi

chmod +x deploy/scripts/*.sh

cat <<EOF

=== Worker installed in this clone ===

Run manually (foreground):
  source .venv/bin/activate
  python -m worker

=== systemd install (production) ===

1. Copy or clone this repo to /opt/gene-autoannotator
2. Run this install script there so .venv exists
3. Install config and unit:

   sudo mkdir -p /etc/gene-autoannotator
   sudo cp worker.env /etc/gene-autoannotator/worker.env
   sudo cp deploy/systemd/gene-autoannotator-worker.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now gene-autoannotator-worker

Check status: sudo systemctl status gene-autoannotator-worker

EOF
