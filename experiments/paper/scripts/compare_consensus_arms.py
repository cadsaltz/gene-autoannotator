#!/usr/bin/env python3
"""Compare consensus-arms against arm A using the reviewer labels.

    PYTHONPATH=. python experiments/paper/scripts/compare_consensus_arms.py \
      --run-dir experiments/paper/results/consensus-arms/<run> \
      --labels experiments/paper/results/model_spread_15k/labels \
      --out experiments/paper/results/consensus-arms/<run>/compare/

Writes ``scoreboard.csv`` (per-arm needles found / missed / false positives; ``recall_labeled`` counts only
labeled finds, ``recall_upper_bound`` also counts UNLABELED values on needle fields; ``fp`` counts only
labeled false positives, so ``unlabeled_non_needle`` - unjudged non-null values on no-needle fields, e.g. B
merges or D reassembled strings - is reported beside it and ``fp_upper_bound`` = ``fp`` +
``unlabeled_non_needle``) and
``vs_A.md`` (needle-by-needle and false-positive diffs of every other arm vs A, on the
trials both arms completed).  Only labeled trials are scored.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from experiments.paper.runners.consensus_arms_io import load_labels, packet_stem  # noqa: E402
from experiments.paper.scripts import consensus_arms_review as review  # noqa: E402
from experiments.paper.scripts.build_consensus_arms_spreadsheet import arm_name  # noqa: E402

SCOREBOARD_COLUMNS = (
    "arm", "n_trials", "n_labeled_trials", "needles_total", "found", "found_clean", "found_padded",
    "missed", "fp", "unlabeled", "unlabeled_on_needles", "unlabeled_non_needle", "correctly_empty",
    "extra_supported", "recall_labeled", "recall_upper_bound", "fp_upper_bound", "status",
)


def discover_arms(run_dir: Path) -> dict[str, Path]:
    arms = {}
    for d in sorted(run_dir.glob("arm_*")):
        if d.is_dir() and (d / "records.jsonl").is_file():
            arms[arm_name(d)] = d
    return arms


def score_arm(arm_dir: Path, labels: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Return ``{trial_id: {"buckets": tally, "res": evaluation}}`` for labeled trials."""
    out: dict[str, dict[str, Any]] = {}
    with (arm_dir / "records.jsonl").open() as fh:
        for line in fh:
            if not line.strip():
                continue
            rec = json.loads(line)
            doc = labels.get(packet_stem(rec["trial_id"]))
            if doc is None:
                continue
            res = review.evaluate_arm_output(doc, rec.get("candidates") or {}, rec.get("arm_output"))
            out[rec["trial_id"]] = {"buckets": review.tally(res, doc), "res": res}
    return out


def scoreboard_row(arm: str, arm_dir: Path, scored: dict[str, dict[str, Any]]) -> dict[str, Any]:
    manifest = json.loads((arm_dir / "manifest.json").read_text()) if (arm_dir / "manifest.json").is_file() else {}
    n_records = sum(1 for line in (arm_dir / "records.jsonl").open() if line.strip())
    totals = {k: 0 for k in ("found_clean", "found_padded", "missed", "fp", "unlabeled",
                             "correctly_empty", "extra_supported",
                             "unlabeled_needles", "unlabeled_non_needle")}
    needles = 0
    for item in scored.values():
        b = item["buckets"]
        needles += len(b["_needle_fields"])
        for k in totals:
            totals[k] += len(b[k])
    found = totals["found_clean"] + totals["found_padded"]
    unl_needles = totals.pop("unlabeled_needles")
    return {
        "arm": arm, "n_trials": n_records, "n_labeled_trials": len(scored), "needles_total": needles,
        "found": found, **totals, "unlabeled_on_needles": unl_needles,
        "recall_labeled": f"{found / needles:.3f}" if needles else "",
        "recall_upper_bound": f"{(found + unl_needles) / needles:.3f}" if needles else "",
        "fp_upper_bound": totals["fp"] + totals["unlabeled_non_needle"],
        "status": manifest.get("status", ""),
    }


def _found_set(item: dict[str, Any]) -> set[str]:
    b = item["buckets"]
    return set(b["found_clean"]) | set(b["found_padded"])


def _needle_state(item: dict[str, Any], fld: str) -> str:
    """found / unresolved (UNLABELED non-null value, needs judging) / missed."""
    b = item["buckets"]
    if fld in set(b["found_clean"]) | set(b["found_padded"]):
        return "found"
    if fld in b["unlabeled_needles"]:
        return "unresolved"
    return "missed"


CAVEAT = (
    "> **Caveat:** needle values that match no labeled extractor candidate (e.g. judge rewrites) are "
    "UNLABELED and listed as *unresolved, needs judging* - they are not counted as lost or missed.\n>\n"
    "> **`fp` alone is incomplete when UNLABELED > 0:** a non-null value on a no-needle field that no "
    "labeled candidate proposed (judge merges, reassembled Arm D strings) is UNLABELED, not `fp`. It is "
    "reported as `unlabeled_non_needle` (FP risk) and `fp_upper_bound` = `fp` + `unlabeled_non_needle` "
    "in `scoreboard.csv`; treat `fp` as a lower bound until those values are judged."
)


def diff_vs_a(arm: str, scored: dict[str, dict[str, Any]], a_scored: dict[str, dict[str, Any]]) -> str:
    shared = sorted(set(scored) & set(a_scored))
    gained, lost, same_found, same_missed = [], [], 0, 0
    unresolved: list[tuple[str, str, str, str]] = []
    fp_new, fp_removed = [], []
    risk_new: list[tuple[str, str]] = []
    risk_total = 0
    for tid in shared:
        a_item, item = a_scored[tid], scored[tid]
        needles = item["buckets"]["_needle_fields"]
        a_found, found = _found_set(a_item), _found_set(item)
        for fld in needles:
            a_state, state = _needle_state(a_item, fld), _needle_state(item, fld)
            if "unresolved" in (a_state, state):
                unresolved.append((tid, fld, a_state, state))
            elif fld in found and fld not in a_found:
                gained.append((tid, fld))
            elif fld in a_found and fld not in found:
                lost.append((tid, fld))
            elif fld in found:
                same_found += 1
            else:
                same_missed += 1
        a_fp, fp = set(a_item["buckets"]["fp"]), set(item["buckets"]["fp"])
        fp_new += [(tid, f) for f in sorted(fp - a_fp)]
        fp_removed += [(tid, f) for f in sorted(a_fp - fp)]
        a_risk, risk = set(a_item["buckets"]["unlabeled_non_needle"]), set(item["buckets"]["unlabeled_non_needle"])
        risk_total += len(risk)
        risk_new += [(tid, f) for f in sorted(risk - a_risk)]

    def table(title: str, rows: list[tuple[str, str]]) -> list[str]:
        lines = [f"### {title} ({len(rows)})", ""]
        if not rows:
            return lines + ["_none_", ""]
        lines += ["| trial | field |", "|---|---|"] + [f"| {t} | {f} |" for t, f in rows]
        return lines + [""]

    lines = [
        f"## Arm {arm} vs A", "",
        f"Shared labeled trials: {len(shared)}. Needles found by both: {same_found}; "
        f"missed by both: {same_missed}; unresolved (needs judging): {len(unresolved)}.", "",
    ]
    lines += table(f"Needles gained vs A (found by {arm}, missed by A)", gained)
    lines += table(f"Needles lost vs A (found by A, missed by {arm})", lost)
    lines += [f"### Unresolved - needs judging ({len(unresolved)})", ""]
    if unresolved:
        lines += [f"| trial | field | A | {arm} |", "|---|---|---|---|"]
        lines += [f"| {t} | {f} | {a} | {b} |" for t, f, a, b in unresolved]
    else:
        lines.append("_none_")
    lines.append("")
    lines += table(f"False positives new vs A (FP in {arm}, not in A)", fp_new)
    lines += table(f"False positives removed vs A (FP in A, not in {arm})", fp_removed)
    lines += [f"_`fp` is incomplete: {arm} has {risk_total} unjudged non-null value(s) on no-needle fields "
              "(`unlabeled_non_needle`, FP risk)._", ""]
    lines += table(f"Unjudged no-needle values new vs A (FP risk in {arm}, not in A)", risk_new)
    return "\n".join(lines)


def compare(run_dir: Path, labels_dir: Path, out_dir: Path) -> tuple[Path, Path]:
    arms = discover_arms(run_dir)
    if "A" not in arms:
        raise SystemExit(f"arm A not found under {run_dir} (found: {sorted(arms) or 'none'})")
    labels = load_labels(labels_dir)
    if not labels:
        raise SystemExit(f"no t*.json labels in {labels_dir}")
    scored = {arm: score_arm(d, labels) for arm, d in arms.items()}
    order = ["A"] + [a for a in arms if a != "A"]

    out_dir.mkdir(parents=True, exist_ok=True)
    board = out_dir / "scoreboard.csv"
    with board.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=SCOREBOARD_COLUMNS)
        w.writeheader()
        for arm in order:
            w.writerow(scoreboard_row(arm, arms[arm], scored[arm]))

    md = out_dir / "vs_A.md"
    parts = [f"# Consensus arms vs A\n\n{CAVEAT}\n\nRun: `{run_dir}`\n"]
    parts += [diff_vs_a(arm, scored[arm], scored["A"]) for arm in order[1:]]
    if len(order) == 1:
        parts.append("_Only arm A present; nothing to compare._\n")
    md.write_text("\n".join(parts) + "\n")
    return board, md


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--run-dir", required=True, type=Path, help="<run_id> dir containing arm_*/")
    p.add_argument("--labels", required=True, type=Path)
    p.add_argument("--out", required=True, type=Path, help="output directory")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    board, md = compare(args.run_dir.expanduser(), args.labels.expanduser(), args.out.expanduser())
    print(f"wrote {board}\nwrote {md}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
