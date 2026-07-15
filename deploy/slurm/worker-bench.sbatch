#!/bin/bash
#SBATCH --job-name=gaa-bench
#SBATCH --partition=REPLACE_ME
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=16
#SBATCH --mem=64G
#SBATCH --time=48:00:00
#SBATCH --output=logs/%x-%j.out

set -euo pipefail
mkdir -p logs

# Optional: module load docker  # if required on this site

IMAGE="${IMAGE:-DOCKERHUB_USER/gene-autoannotator-worker:TAG}"
SCRATCH="${SCRATCH:-$HOME/gene-autoannotator-runs}"
RUN_DIR="$SCRATCH/runs/${SLURM_JOB_ID}"
mkdir -p "$RUN_DIR"

# Prefer repo checkout on shared FS, or copy script to $SCRATCH/bin
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

"${SCRIPT_DIR}/scripts/run-worker-bench.sh" \
  --image "$IMAGE" \
  --jobs "$SCRATCH/batches/mtb_100.jsonl" \
  --output-dir "$RUN_DIR/gen_json" \
  --report "$RUN_DIR/report.json" \
  --models-dir "$SCRATCH/ollama-models" \
  --cache-dir "$RUN_DIR/cache" \
  --env-file "$SCRATCH/config/worker.bench.env" \
  --gpus '"device=0"'
