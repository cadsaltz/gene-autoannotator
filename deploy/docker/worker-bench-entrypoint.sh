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

if [[ "${REQUIRE_GPU:-1}" == "1" ]] && ! command -v nvidia-smi >/dev/null 2>&1; then
  echo "error: nvidia-smi not found; refuse to run performance bench without GPU (set REQUIRE_GPU=0 to override)" >&2
  exit 2
fi

export OLLAMA_MODELS="$MODELS_DIR"
export WORKER_CACHE_DIR="$CACHE_DIR"
export WORKER_OUTPUT_DIR="$OUTPUT_DIR"
export WORKER_ENV_FILE="${WORKER_ENV_FILE:-$OUTPUT_DIR/worker.env}"

ARGS=(bench --jobs "$JOBS_PATH" --output-dir "$OUTPUT_DIR" --report "$REPORT_PATH" --cache "$CACHE_MODE")
if [[ -n "${WORKER_BENCH_SLOTS:-}" ]]; then
  ARGS+=(--slots "$WORKER_BENCH_SLOTS")
fi

# Allow passthrough args after "--" from docker run
if [[ "${1:-}" == "bench" ]] || [[ "${1:-}" == --* ]]; then
  exec python -m worker "$@"
fi
exec python -m worker "${ARGS[@]}" "$@"
