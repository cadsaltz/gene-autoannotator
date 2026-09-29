#!/usr/bin/env bash
set -euo pipefail
URL="${1:?Usage: $0 http://backend-host:8000}"
curl -fsS "$URL/healthz" >/dev/null
echo "OK: backend reachable at $URL"
