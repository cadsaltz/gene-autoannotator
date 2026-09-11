#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<EOF
Usage: $0 [OPTIONS]

Run one bounded queue-drain worker allocation in Apptainer (worker run).

Required:
  --models-dir PATH     Ollama models directory
  --output-dir PATH     Annotation output directory
  --env-file PATH       Apptainer --env-file (BACKEND_URL, WORKER_API_TOKEN, fleet)

Optional:
  --cache-dir PATH      Cache directory (default: <output-dir>/../cache)
  --image NAME          Apptainer/SIF or Docker image ref (default: \$IMAGE or
                        gene-autoannotator-worker:latest)
  --dry-run             Print apptainer command and exit
  -h, --help            Show this help

Environment:
  IMAGE                 Default image if --image not set
EOF
}

abspath() {
  local target="$1"
  if command -v realpath >/dev/null 2>&1; then
    realpath -m "$target"
  elif command -v readlink >/dev/null 2>&1 && [[ -e "$target" ]]; then
    readlink -f "$target"
  else
    local dir base
    dir="$(dirname "$target")"
    base="$(basename "$target")"
    mkdir -p "$dir"
    echo "$(cd "$dir" && pwd)/$base"
  fi
}

OUTPUT_DIR=""
MODELS_DIR=""
CACHE_DIR=""
ENV_FILE=""
IMAGE="${IMAGE:-gene-autoannotator-worker:latest}"
DRY_RUN=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --output-dir)
      OUTPUT_DIR="$2"
      shift 2
      ;;
    --models-dir)
      MODELS_DIR="$2"
      shift 2
      ;;
    --cache-dir)
      CACHE_DIR="$2"
      shift 2
      ;;
    --env-file)
      ENV_FILE="$2"
      shift 2
      ;;
    --image)
      IMAGE="$2"
      shift 2
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    -h | --help)
      usage
      exit 0
      ;;
    *)
      echo "error: unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

missing=()
[[ -z "$OUTPUT_DIR" ]] && missing+=(--output-dir)
[[ -z "$MODELS_DIR" ]] && missing+=(--models-dir)
[[ -z "$ENV_FILE" ]] && missing+=(--env-file)
if [[ ${#missing[@]} -gt 0 ]]; then
  echo "error: missing required option(s): ${missing[*]}" >&2
  usage >&2
  exit 1
fi

if [[ -z "$CACHE_DIR" ]]; then
  CACHE_DIR="$(dirname "$OUTPUT_DIR")/cache"
fi

mkdir -p "$OUTPUT_DIR" "$CACHE_DIR" "$MODELS_DIR"

OUTPUT_DIR="$(abspath "$OUTPUT_DIR")"
CACHE_DIR="$(abspath "$CACHE_DIR")"
MODELS_DIR="$(abspath "$MODELS_DIR")"
ENV_FILE="$(abspath "$ENV_FILE")"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "error: env file not found: $ENV_FILE" >&2
  exit 1
fi

# Same Apptainer shape as the lead's proven SCRI autoannotation job, but for
# backend queue drain (worker run) instead of local JSONL bench.
APPTAINER_CMD=(
  apptainer exec --no-home --writable-tmpfs --nv --cwd=/app
  --bind "$OUTPUT_DIR:/out/annotations"
  --bind "$CACHE_DIR:/out/cache"
  --bind "$MODELS_DIR:/models"
  --bind "$ENV_FILE:/app/worker.env:ro"
  --env-file "$ENV_FILE"
  --env "OLLAMA_MODELS=/models"
  --env "WORKER_OUTPUT_DIR=/out/annotations"
  --env "WORKER_CACHE_DIR=/out/cache"
  --env "WORKER_ENV_FILE=/app/worker.env"
  "$IMAGE"
  /usr/local/bin/worker-run-entrypoint.sh
)

if [[ "$DRY_RUN" -eq 1 ]]; then
  printf '%q ' "${APPTAINER_CMD[@]}"
  printf '\n'
  exit 0
fi

exec "${APPTAINER_CMD[@]}"
