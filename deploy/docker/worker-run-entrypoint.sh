#!/usr/bin/env bash
# One-shot queue drain inside the worker image (Slurm / Apptainer child).
set -euo pipefail

OUTPUT_DIR="${WORKER_OUTPUT_DIR:-/out/annotations}"
CACHE_DIR="${WORKER_CACHE_DIR:-/out/cache}"
MODELS_DIR="${OLLAMA_MODELS:-/models}"

mkdir -p "$OUTPUT_DIR" "$CACHE_DIR" "$MODELS_DIR"

if [[ "${REQUIRE_GPU:-1}" == "1" ]] && ! command -v nvidia-smi >/dev/null 2>&1; then
  echo "error: nvidia-smi not found; refuse to run without GPU (set REQUIRE_GPU=0 to override)" >&2
  exit 2
fi

export OLLAMA_MODELS="$MODELS_DIR"
export WORKER_CACHE_DIR="$CACHE_DIR"
export WORKER_OUTPUT_DIR="$OUTPUT_DIR"

# Apptainer mounts the operator env file read-only so it can still use that
# file for --env-file injection. Bootstrap also persists detected fleet values,
# so give Python an allocation-local writable copy.
if [[ -n "${WORKER_ENV_FILE:-}" ]]; then
  writable_env="$(mktemp "${TMPDIR:-/tmp}/worker.env.XXXXXX")"
  cp -- "$WORKER_ENV_FILE" "$writable_env"
  chmod u+rw "$writable_env"
  export WORKER_ENV_FILE="$writable_env"
fi

# Full override when the first arg is the run subcommand.
if [[ "${1:-}" == "run" ]]; then
  exec python -m worker "$@"
fi
exec python -m worker run "$@"
