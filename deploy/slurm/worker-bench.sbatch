#!/bin/bash
#SBATCH --job-name=gaa-tbrucei-gemma4
#SBATCH --partition=REPLACE_ME
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=16
#SBATCH --mem=128G
#SBATCH --time=168:00:00
#SBATCH --output=logs/%x-%j.out

set -euo pipefail
mkdir -p logs

# Optional: module load docker  # if required on this site

IMAGE="${IMAGE:-gene-autoannotator-worker:gemma4-solo}"
SCRATCH="${SCRATCH:-$HOME/gene-autoannotator-runs}"
RUN_DIR="$SCRATCH/runs/${SLURM_JOB_ID:-manual}"
mkdir -p "$RUN_DIR"

# Prefer repo checkout on shared FS, or copy script to $SCRATCH/bin
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

"${SCRIPT_DIR}/scripts/run-worker-bench.sh" \
  --image "$IMAGE" \
  --jobs "${JOBS:-$SCRIPT_DIR/batches/tbrucei-treu927-ge10-papers.jsonl}" \
  --output-dir "$RUN_DIR/gen_json" \
  --report "$RUN_DIR/report.json" \
  --models-dir "$SCRATCH/ollama-models" \
  --cache-dir "$RUN_DIR/cache" \
  --env-file "${ENV_FILE:-$SCRIPT_DIR/docker/worker.bench.tbrucei-gemma4.env}" \
  --slots 2 \
  --gpus '"device=0"'
