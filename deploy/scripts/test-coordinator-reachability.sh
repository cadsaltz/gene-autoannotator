#!/usr/bin/env bash
set -euo pipefail
URL="${1:?Usage: $0 http://coordinator-host:8000}"
curl -sf "${URL%/}/health" | python3 -m json.tool
echo "OK: coordinator reachable at $URL"
