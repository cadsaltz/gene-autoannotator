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

# Full override when the first arg is the run subcommand.
if [[ "${1:-}" == "run" ]]; then
  exec python -m worker "$@"
fi
exec python -m worker run "$@"
