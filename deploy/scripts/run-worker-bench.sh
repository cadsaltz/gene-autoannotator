#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<EOF
Usage: $0 [OPTIONS]

Run the worker benchmark in Docker with host-mounted jobs, outputs, cache, and models.

Required:
  --jobs PATH           Batch JSONL file (mounted at /jobs/batch.jsonl)
  --output-dir PATH     Annotation output directory
  --report PATH         Bench report JSON path
  --models-dir PATH     Ollama models directory

Optional:
  --cache-dir PATH      Cache directory (default: <output-dir>/../cache)
  --env-file PATH       Docker --env-file for overrides
  --image NAME          Docker image (default: gene-autoannotator-worker:latest or \$IMAGE)
  --slots N             Set WORKER_BENCH_SLOTS env
  --cache MODE          cold|warm (default: cold)
  --gpus SPEC           Docker --gpus value (default: "device=0")
  --dry-run             Print docker command and exit
  -h, --help            Show this help

Environment:
  IMAGE                 Default image if --image not set
  GPUS                  Default GPU spec if --gpus not set
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

JOBS=""
OUTPUT_DIR=""
REPORT=""
MODELS_DIR=""
CACHE_DIR=""
ENV_FILE=""
IMAGE="${IMAGE:-gene-autoannotator-worker:latest}"
GPUS="${GPUS:-\"device=0\"}"
CACHE="cold"
SLOTS=""
DRY_RUN=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --jobs)
      JOBS="$2"
      shift 2
      ;;
    --output-dir)
      OUTPUT_DIR="$2"
      shift 2
      ;;
    --report)
      REPORT="$2"
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
    --slots)
      SLOTS="$2"
      shift 2
      ;;
    --cache)
      CACHE="$2"
      shift 2
      ;;
    --gpus)
      GPUS="$2"
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
[[ -z "$JOBS" ]] && missing+=(--jobs)
[[ -z "$OUTPUT_DIR" ]] && missing+=(--output-dir)
[[ -z "$REPORT" ]] && missing+=(--report)
[[ -z "$MODELS_DIR" ]] && missing+=(--models-dir)
if [[ ${#missing[@]} -gt 0 ]]; then
  echo "error: missing required option(s): ${missing[*]}" >&2
  usage >&2
  exit 1
fi

if [[ -z "$CACHE_DIR" ]]; then
  CACHE_DIR="$(dirname "$OUTPUT_DIR")/cache"
fi

mkdir -p "$OUTPUT_DIR" "$(dirname "$REPORT")" "$CACHE_DIR" "$MODELS_DIR"

JOBS="$(abspath "$JOBS")"
OUTPUT_DIR="$(abspath "$OUTPUT_DIR")"
REPORT="$(abspath "$REPORT")"
CACHE_DIR="$(abspath "$CACHE_DIR")"
MODELS_DIR="$(abspath "$MODELS_DIR")"
REPORT_DIR="$(dirname "$REPORT")"

if [[ ! -f "$JOBS" ]]; then
  echo "error: jobs file not found: $JOBS" >&2
  exit 1
fi

if [[ -n "$ENV_FILE" ]]; then
  ENV_FILE="$(abspath "$ENV_FILE")"
  if [[ ! -f "$ENV_FILE" ]]; then
    echo "error: env file not found: $ENV_FILE" >&2
    exit 1
  fi
fi

# -t allocates a pseudo-TTY so worker bench can enable the live dashboard
# (sys.stdout.isatty()). Without it, Docker pipes stdout and the dashboard
# falls back to scrolling logs. Use --no-dashboard / WORKER_BENCH_DASHBOARD=0
# inside the container if you need linear logs (e.g. Slurm capture).
DOCKER_CMD=(
  docker run --rm -t --gpus "$GPUS"
  -v "$JOBS:/jobs/batch.jsonl:ro"
  -v "$OUTPUT_DIR:/out/annotations"
  -v "$REPORT_DIR:/out/reports"
  -v "$CACHE_DIR:/out/cache"
  -v "$MODELS_DIR:/models"
)

if [[ -n "$ENV_FILE" ]]; then
  DOCKER_CMD+=(--env-file "$ENV_FILE")
fi

DOCKER_CMD+=(
  -e "CACHE_MODE=$CACHE"
  -e "REPORT_PATH=/out/reports/$(basename "$REPORT")"
  -e "OLLAMA_MODELS=/models"
  -e "WORKER_OUTPUT_DIR=/out/annotations"
  -e "WORKER_CACHE_DIR=/out/cache"
)

if [[ -n "$SLOTS" ]]; then
  DOCKER_CMD+=(-e "WORKER_BENCH_SLOTS=$SLOTS")
fi

DOCKER_CMD+=("$IMAGE")

if [[ "$DRY_RUN" -eq 1 ]]; then
  printf '%q ' "${DOCKER_CMD[@]}"
  printf '\n'
  exit 0
fi

exec "${DOCKER_CMD[@]}"
