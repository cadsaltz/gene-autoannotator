#!/bin/bash
#SBATCH --partition=gpu-core
#SBATCH --account=ma_lab_main
#SBATCH --job-name=gene-autoannotator-run
#SBATCH --nodes=1
#SBATCH --cpus-per-task=32
#SBATCH --ntasks=1
#SBATCH --mem=480g
#SBATCH --time=48:00:00
#SBATCH --gpus=1
#SBATCH --output=gene-autoannotator-run-%j.out

# One-shot queue drain: Apptainer worker claims one backend job then exits.
# Job name MUST stay gene-autoannotator-run — dispatcher counts it via squeue.
# Heartbeats renew the backend lease while the allocation runs; requeue after a
# killed allocation is delayed by LEASE_SECONDS on the backend.
set -euo pipefail

: "${GAA_REPO_ROOT:?GAA_REPO_ROOT must be set (dispatcher exports it)}"

WORKER_IMAGE="${WORKER_IMAGE:?WORKER_IMAGE must be set (SIF path or image ref)}"
WORKER_RUN_ENV_FILE="${WORKER_RUN_ENV_FILE:?WORKER_RUN_ENV_FILE must be set}"
WORKER_MODELS_DIR="${WORKER_MODELS_DIR:-${GAA_REPO_ROOT}/models}"
WORKER_CACHE_DIR="${WORKER_CACHE_DIR:-${GAA_REPO_ROOT}/.cache/worker-run}"
WORKER_OUTPUT_DIR="${WORKER_OUTPUT_DIR:-${GAA_REPO_ROOT}/gen_json}"

"${GAA_REPO_ROOT}/deploy/scripts/run-worker-run.sh" \
  --image "${WORKER_IMAGE}" \
  --env-file "${WORKER_RUN_ENV_FILE}" \
  --models-dir "${WORKER_MODELS_DIR}" \
  --cache-dir "${WORKER_CACHE_DIR}" \
  --output-dir "${WORKER_OUTPUT_DIR}"
