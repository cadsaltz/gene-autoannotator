#!/bin/bash
#SBATCH --job-name=gene-autoannotator-run
#SBATCH --partition=REPLACE_ME
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=16
#SBATCH --mem=64G
#SBATCH --time=48:00:00
#SBATCH --output=gene-autoannotator-run-%j.out

set -euo pipefail

# This script assumes the repository and Python environment are available on
# the compute node. Set these environment variables before running dispatcher:
# BACKEND_URL, WORKER_API_TOKEN, and any worker/model configuration.
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

python -m worker run --claim-one
