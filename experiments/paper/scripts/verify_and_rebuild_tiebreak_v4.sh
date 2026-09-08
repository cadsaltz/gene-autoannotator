#!/usr/bin/env bash
# Verify tie-break paper-*-v4 runs and rebuild tiebreak_team_review.xlsx.
# Intended to run on laptop sch (or any host that has the results tree).
set -euo pipefail

REPO_ROOT="${REPO_ROOT:-$HOME/sch/gene-autoannotator}"
RESULTS_ROOT="${RESULTS_ROOT:-$REPO_ROOT/experiments/paper/results}"
NN_DIR="${NN_DIR:-$RESULTS_ROOT/tiebreak-non-nonsense/paper-non-nonsense-v4}"
NS_DIR="${NS_DIR:-$RESULTS_ROOT/tiebreak-nonsense/paper-nonsense-v4}"
OUTPUT_XLSX="${OUTPUT_XLSX:-$RESULTS_ROOT/tiebreak_team_review.xlsx}"
BUILD_SCRIPT="${BUILD_SCRIPT:-$REPO_ROOT/experiments/paper/scripts/build_tiebreak_team_review_spreadsheet.py}"

REQUIRED_IDS=(
  general-multi-field-001
  biology-multi-field-001
  general-nonsense-multi-field-001
  biology-nonsense-multi-field-001
)

die() { echo "ERROR: $*" >&2; exit 1; }

verify_run() {
  local label="$1"
  local run_dir="$2"
  local expected_lo="$3"
  local expected_hi="$4"

  echo "==== $label ===="
  [[ -d "$run_dir" ]] || die "missing run dir: $run_dir"
  [[ -f "$run_dir/manifest.json" ]] || die "missing manifest.json in $run_dir"
  [[ -f "$run_dir/aggregate.csv" ]] || die "missing aggregate.csv in $run_dir"
  [[ -f "$run_dir/records.jsonl" ]] || die "missing records.jsonl in $run_dir"

  python3 - "$run_dir" "$expected_lo" "$expected_hi" <<'PY'
import csv, json, sys
from pathlib import Path

run_dir = Path(sys.argv[1])
lo, hi = int(sys.argv[2]), int(sys.argv[3])
manifest = json.loads((run_dir / "manifest.json").read_text())
records = [json.loads(line) for line in (run_dir / "records.jsonl").read_text().splitlines() if line.strip()]
with (run_dir / "aggregate.csv").open(newline="") as fh:
    aggregate = list(csv.DictReader(fh))
overall = next(r for r in aggregate if r.get("scope") == "overall" and r.get("value") == "all")
case_ids = sorted({r["case_id"] for r in records})
print(f"run_dir={run_dir}")
print(f"dry_run={manifest.get('dry_run')!r}")
print(f"manifest.case_count={manifest.get('case_count')}")
print(f"records.case_count={len(case_ids)}")
print(f"aggregate.overall.case_count={overall.get('case_count')}")
print(f"consensus_match_soft_rate={overall.get('consensus_match_soft_rate')}")
print(f"baseline_match_soft_rate={overall.get('baseline_match_soft_rate')}")
print(f"necessity_delta={overall.get('necessity_delta')}")
print(f"llm_invoked_rate={overall.get('llm_invoked_rate')}")
print(f"expect_llm_calibration_rate={overall.get('expect_llm_calibration_rate')}")
print(f"invention_rate={overall.get('invention_rate')}")
if str(manifest.get("experiment_id") or run_dir.parent.name) == "tiebreak-nonsense":
    print(f"nonsense_majority_adoption_rate={overall.get('nonsense_majority_adoption_rate')}")
if manifest.get("dry_run") is not False:
    raise SystemExit(f"expected dry_run false, got {manifest.get('dry_run')!r}")
count = int(overall["case_count"])
if not (lo <= count <= hi):
    raise SystemExit(f"case_count {count} outside expected range [{lo}, {hi}]")
print("case_ids:")
for cid in case_ids:
    print(f"  {cid}")
special = [cid for cid in case_ids if "unanimous" in cid or "hard-split" in cid or "hard_split" in cid]
print("unanimous_or_hard_split_ids=" + (",".join(special) if special else "<none>"))
PY
}

echo "REPO_ROOT=$REPO_ROOT"
echo "RESULTS_ROOT=$RESULTS_ROOT"
echo "OUTPUT_XLSX=$OUTPUT_XLSX"

verify_run "non-nonsense v4" "$NN_DIR" 24 28
verify_run "nonsense v4" "$NS_DIR" 16 20

echo "==== required case_ids across both runs ===="
python3 - "$NN_DIR" "$NS_DIR" "${REQUIRED_IDS[@]}" <<'PY'
import json, sys
from pathlib import Path

nn, ns = Path(sys.argv[1]), Path(sys.argv[2])
required = sys.argv[3:]
ids = set()
for run_dir in (nn, ns):
    for line in (run_dir / "records.jsonl").read_text().splitlines():
        if line.strip():
            ids.add(json.loads(line)["case_id"])
missing = [cid for cid in required if cid not in ids]
for cid in required:
    print(f"{cid}: {'FOUND' if cid in ids else 'MISSING'}")
if missing:
    raise SystemExit("missing required case_ids: " + ", ".join(missing))
print("all required case_ids present")
PY

echo "==== rebuild spreadsheet ===="
[[ -f "$BUILD_SCRIPT" ]] || die "missing build script: $BUILD_SCRIPT"
python3 "$BUILD_SCRIPT" "$NN_DIR" "$NS_DIR" --output "$OUTPUT_XLSX"
ls -lh "$OUTPUT_XLSX"
echo "DONE"
