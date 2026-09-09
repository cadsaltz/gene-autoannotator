#!/usr/bin/env bash
# Export team-review xlsx from a tie-break run directory.
#
# Preferred: pass --spreadsheet on run_tiebreak_consensus so the workbook is
# written at the end of a successful run. This script is for post-hoc export.
#
# Usage:
#   bash experiments/paper/scripts/export_tiebreak_spreadsheet.sh \
#     --run-dir experiments/paper/results/tiebreak-consensus/paper-tiebreak-v5
#
# Optional:
#   --output PATH  default: <run-dir>/team_review.xlsx
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
RUN_DIR=""
OUTPUT=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --run-dir) RUN_DIR="$2"; shift 2 ;;
    --output) OUTPUT="$2"; shift 2 ;;
    -h|--help) sed -n '2,14p' "$0"; exit 0 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

if [[ -z "$RUN_DIR" ]]; then
  echo "required: --run-dir PATH (tie-break run directory with manifest/records/aggregate)" >&2
  exit 2
fi

RUN_DIR="$(cd "$ROOT" && realpath "$RUN_DIR")"
for f in manifest.json records.jsonl aggregate.csv; do
  [[ -f "$RUN_DIR/$f" ]] || {
    echo "incomplete run dir: $RUN_DIR (missing $f)" >&2
    exit 1
  }
done

PY="${ROOT}/.venv/bin/python"
[[ -x "$PY" ]] || PY=python3

ARGS=(--run-dir "$RUN_DIR")
[[ -n "$OUTPUT" ]] && ARGS+=(--output "$OUTPUT")

"$PY" "$ROOT/experiments/paper/scripts/build_tiebreak_team_review_spreadsheet.py" "${ARGS[@]}"
