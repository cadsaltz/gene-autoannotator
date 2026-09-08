#!/usr/bin/env python3
"""Build a team-review Excel workbook from tie-break v4 run directories.

Reads ``manifest.json``, ``aggregate.csv``, and ``records.jsonl`` from one or
more ``results/<experiment_id>/<run_id>/`` directories and writes a review
workbook with Summary + Cases sheets.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

HEADER_FILL = PatternFill("solid", fgColor="1F4E79")
HEADER_FONT = Font(bold=True, color="FFFFFF")
SECTION_FILL = PatternFill("solid", fgColor="D6E3F0")
PASS_FILL = PatternFill("solid", fgColor="C6EFCE")
FAIL_FILL = PatternFill("solid", fgColor="FFC7CE")


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_records(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _load_aggregate(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _json_cell(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def _style_header(ws, ncols: int) -> None:
    for col in range(1, ncols + 1):
        cell = ws.cell(1, col)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(wrap_text=True, vertical="center")


def _autosize(ws, max_width: int = 48) -> None:
    for col_cells in ws.columns:
        letter = get_column_letter(col_cells[0].column)
        width = 10
        for cell in col_cells[:200]:
            value = "" if cell.value is None else str(cell.value)
            first_line = value.splitlines()[0] if value else ""
            width = max(width, min(max_width, len(first_line) + 2))
        ws.column_dimensions[letter].width = width


def _case_groups(records: list[dict[str, Any]]) -> dict[str, dict[str, dict[str, Any]]]:
    grouped: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for record in records:
        grouped[record["case_id"]][record["condition"]] = record
    return grouped


def add_summary_sheet(
    wb: Workbook,
    runs: list[tuple[str, Path, dict[str, Any], list[dict[str, str]], list[dict[str, Any]]]],
) -> None:
    ws = wb.active
    ws.title = "Summary"
    ws.append(
        [
            "experiment_id",
            "run_id",
            "run_dir",
            "dry_run",
            "manifest_case_count",
            "record_case_count",
            "aggregate_overall_case_count",
            "consensus_match_soft_rate",
            "baseline_match_soft_rate",
            "necessity_delta",
            "llm_invoked_rate",
            "expect_llm_calibration_rate",
            "invention_rate",
            "nonsense_majority_adoption_rate",
            "required_case_ids_present",
            "unanimous_or_hard_split_ids",
        ]
    )
    required = {
        "general-multi-field-001",
        "biology-multi-field-001",
        "general-nonsense-multi-field-001",
        "biology-nonsense-multi-field-001",
    }
    for experiment_id, run_dir, manifest, aggregate, records in runs:
        overall = next(
            (
                row
                for row in aggregate
                if row.get("scope") == "overall" and row.get("value") == "all"
            ),
            {},
        )
        case_ids = sorted({record["case_id"] for record in records})
        present = sorted(required & set(case_ids))
        special = sorted(
            cid
            for cid in case_ids
            if "unanimous" in cid or "hard-split" in cid or "hard_split" in cid
        )
        ws.append(
            [
                experiment_id,
                manifest.get("run_id", run_dir.name),
                str(run_dir),
                manifest.get("dry_run"),
                manifest.get("case_count"),
                len(case_ids),
                overall.get("case_count"),
                overall.get("consensus_match_soft_rate"),
                overall.get("baseline_match_soft_rate"),
                overall.get("necessity_delta"),
                overall.get("llm_invoked_rate"),
                overall.get("expect_llm_calibration_rate"),
                overall.get("invention_rate"),
                overall.get("nonsense_majority_adoption_rate"),
                ", ".join(present),
                ", ".join(special),
            ]
        )
    _style_header(ws, ws.max_column)
    _autosize(ws)


def add_cases_sheet(
    wb: Workbook,
    runs: list[tuple[str, Path, dict[str, Any], list[dict[str, str]], list[dict[str, Any]]]],
) -> None:
    ws = wb.create_sheet("Cases")
    headers = [
        "experiment_id",
        "run_id",
        "case_id",
        "domain",
        "case_family",
        "field_key",
        "expect_llm",
        "candidates",
        "expected",
        "baseline_observed",
        "baseline_match_soft",
        "consensus_observed",
        "consensus_match_soft",
        "consensus_match_exact",
        "provenance",
        "llm_invoked",
        "expect_llm_matched",
        "invention",
        "review_notes",
    ]
    ws.append(headers)
    _style_header(ws, len(headers))

    for experiment_id, run_dir, manifest, _aggregate, records in runs:
        run_id = manifest.get("run_id", run_dir.name)
        for case_id, by_condition in sorted(_case_groups(records).items()):
            baseline = by_condition.get("no_consensus_pick_extractor_0", {})
            consensus = by_condition.get("hybrid_consensus", {})
            seed = consensus or baseline
            row = [
                experiment_id,
                run_id,
                case_id,
                seed.get("domain"),
                seed.get("case_family"),
                seed.get("field_key"),
                seed.get("expect_llm"),
                _json_cell(seed.get("candidates")),
                _json_cell(seed.get("expected")),
                _json_cell(baseline.get("observed")),
                baseline.get("match_soft"),
                _json_cell(consensus.get("observed")),
                consensus.get("match_soft"),
                consensus.get("match_exact"),
                consensus.get("provenance"),
                consensus.get("llm_invoked"),
                consensus.get("expect_llm_matched"),
                consensus.get("invention"),
                "",
            ]
            ws.append(row)
            excel_row = ws.max_row
            for col, key in ((11, "match_soft"), (13, "match_soft")):
                cell = ws.cell(excel_row, col)
                source = baseline if col == 11 else consensus
                if source.get(key) is True:
                    cell.fill = PASS_FILL
                elif source.get(key) is False:
                    cell.fill = FAIL_FILL
    ws.freeze_panes = "C2"
    _autosize(ws, max_width=60)


def add_aggregate_sheet(
    wb: Workbook,
    runs: list[tuple[str, Path, dict[str, Any], list[dict[str, str]], list[dict[str, Any]]]],
) -> None:
    ws = wb.create_sheet("Aggregate")
    wrote_header = False
    for experiment_id, run_dir, manifest, aggregate, _records in runs:
        if not aggregate:
            continue
        if not wrote_header:
            ws.append(["experiment_id", "run_id", *aggregate[0].keys()])
            _style_header(ws, ws.max_column)
            wrote_header = True
        run_id = manifest.get("run_id", run_dir.name)
        for row in aggregate:
            ws.append([experiment_id, run_id, *[row.get(key) for key in aggregate[0].keys()]])
    if wrote_header:
        _autosize(ws)


def load_run(run_dir: Path) -> tuple[str, Path, dict[str, Any], list[dict[str, str]], list[dict[str, Any]]]:
    run_dir = run_dir.resolve()
    manifest_path = run_dir / "manifest.json"
    records_path = run_dir / "records.jsonl"
    aggregate_path = run_dir / "aggregate.csv"
    missing = [p.name for p in (manifest_path, records_path, aggregate_path) if not p.is_file()]
    if missing:
        raise FileNotFoundError(f"{run_dir} missing required files: {', '.join(missing)}")
    manifest = _load_json(manifest_path)
    experiment_id = str(manifest.get("experiment_id") or run_dir.parent.name)
    return (
        experiment_id,
        run_dir,
        manifest,
        _load_aggregate(aggregate_path),
        _load_records(records_path),
    )


def build_workbook(run_dirs: list[Path], output_path: Path) -> Path:
    runs = [load_run(path) for path in run_dirs]
    wb = Workbook()
    add_summary_sheet(wb, runs)
    add_cases_sheet(wb, runs)
    add_aggregate_sheet(wb, runs)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(output_path)
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build tie-break team-review spreadsheet from v4 (or other) run dirs.",
    )
    parser.add_argument(
        "run_dirs",
        nargs="+",
        type=Path,
        help="One or more results/<experiment_id>/<run_id> directories",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Destination .xlsx path",
    )
    args = parser.parse_args()
    output_path = build_workbook(args.run_dirs, args.output)
    print(f"wrote {output_path} ({output_path.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
