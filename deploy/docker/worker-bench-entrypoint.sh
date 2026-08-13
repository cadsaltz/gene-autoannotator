#!/usr/bin/env bash
set -euo pipefail

JOBS_PATH="${JOBS_PATH:-/jobs/batch.jsonl}"
OUTPUT_DIR="${WORKER_OUTPUT_DIR:-/out/annotations}"
REPORT_PATH="${REPORT_PATH:-/out/reports/report.json}"
CACHE_DIR="${WORKER_CACHE_DIR:-/out/cache}"
MODELS_DIR="${OLLAMA_MODELS:-/models}"
CACHE_MODE="${CACHE_MODE:-cold}"

if [[ ! -f "$JOBS_PATH" ]]; then
  echo "error: jobs file not found at $JOBS_PATH (bind-mount your JSONL)" >&2
  exit 2
fi
mkdir -p "$OUTPUT_DIR" "$(dirname "$REPORT_PATH")" "$CACHE_DIR" "$MODELS_DIR"

REPORT_DIR="$(dirname "$REPORT_PATH")"
if command -v mountpoint >/dev/null 2>&1; then
  for path in "$OUTPUT_DIR" "$CACHE_DIR" "$MODELS_DIR" "$REPORT_DIR"; do
    if ! mountpoint -q "$path"; then
      echo "error: $path is not a bind mount (docker run -v host:$path ...)" >&2
      exit 2
    fi
  done
else
  echo "warning: mountpoint not available; skipping bind-mount validation" >&2
fi

if [[ "${REQUIRE_GPU:-1}" == "1" ]] && ! command -v nvidia-smi >/dev/null 2>&1; then
  echo "error: nvidia-smi not found; refuse to run performance bench without GPU (set REQUIRE_GPU=0 to override)" >&2
  exit 2
fi

export OLLAMA_MODELS="$MODELS_DIR"
export WORKER_CACHE_DIR="$CACHE_DIR"
export WORKER_OUTPUT_DIR="$OUTPUT_DIR"
# Default WORKER_ENV_FILE is repo-root worker.env (/app/worker.env in the image).
# Bind-mount the host file there (run-worker-bench.sh --env-file) for one truth.

ARGS=(bench --jobs "$JOBS_PATH" --output-dir "$OUTPUT_DIR" --report "$REPORT_PATH" --cache "$CACHE_MODE")
if [[ -n "${WORKER_BENCH_SLOTS:-}" ]]; then
  ARGS+=(--slots "$WORKER_BENCH_SLOTS")
fi

# Full override only when the first arg is the bench subcommand.
if [[ "${1:-}" == "bench" ]]; then
  exec python -m worker "$@"
fi
exec python -m worker "${ARGS[@]}" "$@"
