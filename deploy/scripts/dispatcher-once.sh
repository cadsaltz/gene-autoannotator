#!/usr/bin/env bash
# Login-node dispatcher tick: source env, peek queue, sbatch worker-run children.
# Intended for scrontab or a manual pass — not a Slurm parent job.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${REPO_ROOT}"

ENV_FILE="${DISPATCHER_ENV_FILE:-${REPO_ROOT}/dispatcher.env}"
if [[ ! -f "${ENV_FILE}" ]]; then
  echo "error: dispatcher env file not found: ${ENV_FILE}" >&2
  echo "Set DISPATCHER_ENV_FILE or create ${REPO_ROOT}/dispatcher.env" >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090
. "${ENV_FILE}"
set +a

PYTHON="${DISPATCHER_PYTHON:-${REPO_ROOT}/.venv/bin/python}"
if [[ ! -x "${PYTHON}" ]]; then
  PYTHON="$(command -v python3 || command -v python)"
fi

exec "${PYTHON}" -m dispatcher once
