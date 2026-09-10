#!/usr/bin/env python3
"""Team-review workbook for the chunked extractor bias run.

Shows, per source section:
- the reconstructed original excerpt (parts concatenated in order) or prompted
  grep/pass excerpt (never mislabeled as a full paper section for grep)
- each chunk/part text that was actually prompted
- the stored extraction prompt for the first extractor (representative)
- extractor + consensus outputs (one column/block per extractor in the run)
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from experiments.paper.runners.common import (  # noqa: E402
    CONSENSUS_CONDITION,
    extractor_labels_from_observables,
    extractor_labels_from_trial,
)

BIOLOGY_SHEETS = {
    "ecoli-k12-mg1655": "E. coli",
    "mtb-h37rv": "M. tuberculosis",
    "tcruzi-clbrener": "T. cruzi",
}

header_fill = PatternFill("solid", fgColor="1F4E79")
header_font = Font(bold=True, color="FFFFFF")
label_fill = PatternFill("solid", fgColor="D6E3F0")
label_font = Font(bold=True)
trial_fill = PatternFill("solid", fgColor="2E75B6")
chunk_fill = PatternFill("solid", fgColor="548235")
thin = Border(
    left=Side(style="thin", color="B0B0B0"),
    right=Side(style="thin", color="B0B0B0"),
    top=Side(style="thin", color="B0B0B0"),
    bottom=Side(style="thin", color="B0B0B0"),
)


def exact_json(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2)


def load_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text().splitlines()
        if line.strip()
    ]


def load_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path or not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def model_map(trial: dict) -> dict[str, str]:
    models = {}
    for key, metrics in (trial.get("condition_metrics") or {}).items():
        model = metrics.get("model")
        if model:
            models[key] = model
    prompts = trial.get("prompts") or {}
    for key, payload in prompts.items():
        if isinstance(payload, dict) and payload.get("model") and key not in models:
            models[key] = payload["model"]
    return models


def source_group_key(trial: dict) -> tuple:
    section = str(trial.get("section") or "")
    base_section = section.rsplit("#", 1)[0] if "#" in section else section
    fixture_id = trial.get("fixture_trial_id") or trial["trial_id"].rsplit("#", 1)[0]
    return (
        trial.get("trial_pool") or "biology",
        trial.get("profile_id") or "unknown",
        fixture_id,
        trial.get("gene_id"),
        trial.get("pmc_id"),
        base_section,
    )


def part_sort_key(trial: dict) -> tuple[int, str]:
    prep = trial.get("excerpt_preparation") or {}
    part_index = prep.get("part_index")
    if isinstance(part_index, int):
        return (part_index, trial["trial_id"])
    return (1, trial["trial_id"])


def tier_for_parts(parts: list[dict]) -> str:
    ordered = sorted(parts, key=part_sort_key)
    prep0 = ordered[0].get("excerpt_preparation") or {}
    return str(prep0.get("tier") or ("none" if len(ordered) == 1 else "chunk"))


def reconstruct_original_excerpt(parts: list[dict]) -> tuple[str, str, str]:
    """Return (excerpt_text, label, provenance_note)."""
    ordered = sorted(parts, key=part_sort_key)
    preps = [part.get("excerpt_preparation") or {} for part in ordered]
    tier = tier_for_parts(ordered)
    joined = "".join(part.get("excerpt_text") or "" for part in ordered)
    source_chars = ordered[0].get("source_excerpt_chars")
    part_count = preps[0].get("part_count") or len(ordered)
    multipart = len(ordered) > 1 or (
        isinstance(part_count, int) and part_count > 1
    )

    if multipart:
        label = f"ORIGINAL EXCERPT (reconstructed from {len(ordered)} chunk parts)"
        note = (
            f"reconstructed by concatenating {len(ordered)} prompted parts in order"
        )
        if source_chars is not None:
            note += (
                f" (source_excerpt_chars={source_chars}, joined_chars={len(joined)})"
            )
        return joined, label, note

    # Single prompted part: grep/pass/none — never claim full paper section for grep.
    if tier == "grep" or source_chars is None:
        label = "PROMPTED EXCERPT (grep/pass — not full paper section)"
        note = f"single prompted part (tier={tier}); not a full paper section"
        return ordered[0].get("excerpt_text") or "", label, note

    label = "PROMPTED EXCERPT (grep/pass — not full paper section)"
    note = (
        f"single prompted part (tier={tier}, source_excerpt_chars={source_chars})"
    )
    return ordered[0].get("excerpt_text") or "", label, note


def row_height(label: str, value) -> float:
    text = "" if value is None else str(value)
    if (
        "PROMPT" in label
        or "ORIGINAL EXCERPT" in label
        or "PROMPTED EXCERPT" in label
        or "CHUNK TEXT" in label
    ):
        return min(420, max(60, 12 + len(text) // 120))
    if "OUTPUT" in label:
        return min(220, max(45, 12 + len(text) // 80))
    return 18


def write_block(
    ws,
    row: int,
    label: str,
    value,
    *,
    is_trial_header: bool = False,
    is_chunk_header: bool = False,
) -> int:
    ws.merge_cells(start_row=row, start_column=2, end_row=row, end_column=6)
    cell_a = ws.cell(row, 1, label)
    cell_b = ws.cell(row, 2, "" if value is None else str(value))
    cell_a.border = thin
    for col in range(2, 7):
        ws.cell(row, col).border = thin
    cell_a.alignment = Alignment(vertical="top", wrap_text=True)
    cell_b.alignment = Alignment(vertical="top", wrap_text=True)
    if is_trial_header:
        fill, font = trial_fill, header_font
        ws.row_dimensions[row].height = 22
    elif is_chunk_header:
        fill, font = chunk_fill, header_font
        ws.row_dimensions[row].height = 22
    else:
        fill, font = label_fill, label_font
        ws.row_dimensions[row].height = row_height(label, value)
    cell_a.fill = fill
    cell_a.font = font
    if is_trial_header or is_chunk_header:
        for col in range(2, 7):
            cell = ws.cell(row, col)
            cell.fill = fill
            cell.font = font
    return row + 1


def write_source_groups(ws, groups: list[list[dict]]) -> None:
    ws.column_dimensions["A"].width = 48
    ws.column_dimensions["B"].width = 140
    for col in ("C", "D", "E", "F"):
        ws.column_dimensions[col].width = 12

    row = 1
    for group_index, parts in enumerate(groups, start=1):
        ordered = sorted(parts, key=part_sort_key)
        head = ordered[0]
        models = model_map(head)
        original, excerpt_label, original_note = reconstruct_original_excerpt(ordered)
        tier = tier_for_parts(ordered)

        blocks: list[tuple[str, object, str]] = [
            (
                "SOURCE",
                (
                    f"{group_index} of {len(groups)} — "
                    f"{head.get('fixture_trial_id') or head['trial_id']} "
                    f"({len(ordered)} prompted part(s), tier={tier})"
                ),
                "trial",
            ),
            ("fixture_trial_id", head.get("fixture_trial_id"), "label"),
            ("profile_id", head.get("profile_id"), "label"),
            ("gene_id", head.get("gene_id"), "label"),
            ("gene_name", head.get("gene_name"), "label"),
            ("pmc_id", head.get("pmc_id"), "label"),
            ("section_base", str(head.get("section") or "").rsplit("#", 1)[0], "label"),
            ("chunk_tier", tier, "label"),
            ("EXCERPT note", original_note, "label"),
            (excerpt_label, original, "label"),
        ]
        for label, value, kind in blocks:
            row = write_block(
                ws,
                row,
                label,
                value,
                is_trial_header=(kind == "trial"),
            )

        for part in ordered:
            prep = part.get("excerpt_preparation") or {}
            part_index = prep.get("part_index") or 1
            part_count = prep.get("part_count") or len(ordered)
            prompts = part.get("prompts") or {}
            labels = extractor_labels_from_trial(part) or extractor_labels_from_trial(head)
            first_label = labels[0] if labels else "A"
            first_condition = f"extractor_{first_label}"
            extractor_prompt = (prompts.get(first_condition) or {}).get("prompt")
            models_part = model_map(part)
            row = write_block(
                ws,
                row,
                "CHUNK / PROMPTED PART",
                (
                    f"part {part_index} of {part_count} — {part['trial_id']} "
                    f"(chars={prep.get('chars') or len(part.get('excerpt_text') or '')})"
                ),
                is_chunk_header=True,
            )
            row = write_block(ws, row, "trial_id", part["trial_id"])
            row = write_block(ws, row, "excerpt_preparation", exact_json(prep))
            row = write_block(
                ws,
                row,
                "CHUNK TEXT (excerpt_text passed into prompt)",
                part.get("excerpt_text"),
            )
            row = write_block(
                ws,
                row,
                (
                    f"EXTRACTION PROMPT {first_condition} "
                    f"({models_part.get(first_condition, models.get(first_condition, '?'))})"
                ),
                extractor_prompt,
            )
            for label in labels:
                condition = f"extractor_{label}"
                model = models_part.get(condition, models.get(condition, "?"))
                row = write_block(
                    ws,
                    row,
                    f"EXTRACTOR {label} OUTPUT ({model})",
                    exact_json((part.get("outputs") or {}).get(condition)),
                )
            consensus_model = models_part.get(
                CONSENSUS_CONDITION, models.get(CONSENSUS_CONDITION, "?")
            )
            row = write_block(
                ws,
                row,
                f"CONSENSUS OUTPUT ({consensus_model})",
                exact_json((part.get("outputs") or {}).get(CONSENSUS_CONDITION)),
            )
        row += 1

    ws.freeze_panes = "A2"


def _style_header_row(ws, row: int, n_cols: int) -> None:
    for col in range(1, n_cols + 1):
        cell = ws.cell(row, col)
        cell.fill = header_fill
        cell.font = header_font
        cell.border = thin
        cell.alignment = Alignment(wrap_text=True, vertical="center")


def write_summary_sheet(
    ws,
    *,
    manifest: dict,
    observables: list[dict],
    grouped: dict[tuple, list[dict]],
    records_path: Path,
    split_aggregate: Path | None,
    cost_aggregate: Path | None,
    has_chunking: bool = True,
) -> None:
    ws.column_dimensions["A"].width = 28
    for col, width in {
        "B": 22,
        "C": 18,
        "D": 16,
        "E": 18,
        "F": 14,
        "G": 14,
        "H": 18,
        "I": 22,
        "J": 18,
        "K": 20,
    }.items():
        ws.column_dimensions[col].width = width

    model_tags = manifest.get("model_tags") or {}
    tier_counts: Counter[str] = Counter()
    for parts in grouped.values():
        tier_counts[tier_for_parts(parts)] += 1

    row = 1
    title = (
        "Chunking team review — Summary"
        if has_chunking
        else "Bias team review — Summary"
    )
    ws.cell(row, 1, title).font = Font(bold=True, size=14)
    row = 3

    meta_rows = [
        ("records_path", str(records_path)),
        ("experiment_id", manifest.get("experiment_id")),
        ("run_id", manifest.get("run_id")),
        ("git_sha", manifest.get("git_sha")),
        ("model_tags", exact_json(model_tags)),
        ("n_sources", len(grouped)),
        ("n_prompted_parts", len(observables)),
        ("n_fixture_trials", manifest.get("n_fixture_trials")),
        ("n_run_trials", manifest.get("n_run_trials")),
        ("chunk_tier_counts", exact_json(dict(sorted(tier_counts.items())))),
        ("has_excerpt_preparation", has_chunking),
    ]
    ws.cell(row, 1, "Run metadata").font = Font(bold=True, size=12)
    row += 1
    for key, value in meta_rows:
        ws.cell(row, 1, key).font = Font(bold=True)
        ws.cell(row, 2, "" if value is None else str(value))
        ws.cell(row, 2).alignment = Alignment(wrap_text=True, vertical="top")
        if key in {"model_tags", "chunk_tier_counts", "records_path"}:
            ws.row_dimensions[row].height = 36
        row += 1

    row += 1
    ws.cell(row, 1, "Per-trial overview").font = Font(bold=True, size=12)
    row += 1
    overview_headers = [
        "trial_id",
        "pool",
        "profile",
        "gene_id",
        "gene_name",
        "section",
        "tier",
        "part_index/part_count",
        "excerpt_chars",
        "source_excerpt_chars",
    ]
    for col, header in enumerate(overview_headers, start=1):
        ws.cell(row, col, header)
    _style_header_row(ws, row, len(overview_headers))
    row += 1

    for trial in sorted(
        observables,
        key=lambda item: (
            item.get("trial_pool") or "",
            item.get("profile_id") or "",
            item.get("trial_id") or "",
        ),
    ):
        prep = trial.get("excerpt_preparation") or {}
        tier = prep.get("tier") or ("none" if not prep else "?")
        part_index = prep.get("part_index") or 1
        part_count = prep.get("part_count") or 1
        excerpt_chars = prep.get("chars")
        if excerpt_chars is None:
            excerpt_chars = len(trial.get("excerpt_text") or "")
        source_chars = trial.get("source_excerpt_chars")
        values = [
            trial.get("trial_id"),
            trial.get("trial_pool"),
            trial.get("profile_id"),
            trial.get("gene_id"),
            trial.get("gene_name"),
            trial.get("section"),
            tier,
            f"{part_index}/{part_count}",
            excerpt_chars,
            "" if source_chars is None else source_chars,
        ]
        for col, value in enumerate(values, start=1):
            cell = ws.cell(row, col, value)
            cell.border = thin
            cell.alignment = Alignment(wrap_text=True, vertical="top")
        row += 1

    row += 1
    ws.cell(row, 1, "Split aggregate").font = Font(bold=True, size=12)
    row += 1
    split_rows = load_csv_rows(split_aggregate) if split_aggregate else []
    if split_aggregate:
        ws.cell(row, 1, "split_aggregate_path").font = Font(bold=True)
        ws.cell(row, 2, str(split_aggregate))
        row += 1
    if not split_rows:
        ws.cell(row, 1, "(no split aggregate CSV found)")
        row += 2
    else:
        overall = [r for r in split_rows if r.get("scope") == "overall"]
        per_field = [r for r in split_rows if r.get("scope") == "field"]
        split_headers = [
            "scope",
            "field",
            "n_field_values",
            "split_rate",
            "unanimous_rate",
            "partial_rate",
        ]
        ws.cell(row, 1, "Overall + per-field").font = Font(bold=True)
        row += 1
        for col, header in enumerate(split_headers, start=1):
            ws.cell(row, col, header)
        _style_header_row(ws, row, len(split_headers))
        row += 1
        for item in overall + per_field:
            for col, header in enumerate(split_headers, start=1):
                cell = ws.cell(row, col, item.get(header, ""))
                cell.border = thin
            row += 1
        row += 1

    ws.cell(row, 1, "Cost aggregate").font = Font(bold=True, size=12)
    row += 1
    cost_rows = load_csv_rows(cost_aggregate) if cost_aggregate else []
    if cost_aggregate:
        ws.cell(row, 1, "cost_aggregate_path").font = Font(bold=True)
        ws.cell(row, 2, str(cost_aggregate))
        row += 1
    note = (
        "Note: chunking run lacks field_score quality rates; unsupported/supported/"
        "null rates in the cost table are 0. Wall-time/token columns still reflect "
        "this run."
    )
    ws.cell(row, 1, "quality_note").font = Font(bold=True)
    ws.cell(row, 2, note)
    ws.cell(row, 2).alignment = Alignment(wrap_text=True, vertical="top")
    ws.row_dimensions[row].height = 48
    row += 1
    if not cost_rows:
        ws.cell(row, 1, "(no cost aggregate CSV found)")
        row += 1
    else:
        cost_headers = list(cost_rows[0].keys())
        for col, header in enumerate(cost_headers, start=1):
            ws.cell(row, col, header)
        _style_header_row(ws, row, len(cost_headers))
        row += 1
        for item in cost_rows:
            for col, header in enumerate(cost_headers, start=1):
                cell = ws.cell(row, col, item.get(header, ""))
                cell.border = thin
            row += 1

    ws.freeze_panes = "A3"


def _has_excerpt_preparation(observables: list[dict]) -> bool:
    return any(trial.get("excerpt_preparation") is not None for trial in observables)


def _sheet_title(suffix: str, *, has_chunking: bool) -> str:
    if has_chunking:
        return f"Chunk | {suffix}"[:31]
    return suffix[:31]


def _resolve_derived_aggregate(
    derived_value: object,
    *,
    override: Path | None,
) -> Path | None:
    if override is not None:
        return Path(override)
    if not derived_value:
        return None
    path = Path(str(derived_value)) / "aggregate.csv"
    return path if path.is_file() else None


def build_workbook(
    *,
    records_path: Path,
    output_path: Path,
    split_aggregate: Path | None = None,
    cost_aggregate: Path | None = None,
) -> Path:
    rows = load_jsonl(records_path)
    observables = [row for row in rows if row.get("record_type") == "trial_observable"]
    if not observables:
        raise ValueError(f"no trial_observable records in {records_path}")

    grouped: dict[tuple, list[dict]] = defaultdict(list)
    for trial in observables:
        grouped[source_group_key(trial)].append(trial)

    manifest_path = records_path.parent / "manifest.json"
    manifest = (
        json.loads(manifest_path.read_text())
        if manifest_path.is_file()
        else {}
    )
    has_chunking = _has_excerpt_preparation(observables)

    wb = Workbook()
    summary = wb.active
    summary.title = "Summary"
    write_summary_sheet(
        summary,
        manifest=manifest,
        observables=observables,
        grouped=grouped,
        records_path=records_path,
        split_aggregate=split_aggregate,
        cost_aggregate=cost_aggregate,
        has_chunking=has_chunking,
    )

    by_profile: dict[str, list[list[dict]]] = defaultdict(list)
    general_groups: list[list[dict]] = []
    for key, parts in sorted(grouped.items(), key=lambda item: item[0]):
        pool, profile_id = key[0], key[1]
        if pool == "general":
            general_groups.append(parts)
        else:
            by_profile[profile_id].append(parts)

    for profile_id, sheet_suffix in BIOLOGY_SHEETS.items():
        groups = by_profile.get(profile_id) or []
        if not groups:
            continue
        ws = wb.create_sheet(_sheet_title(sheet_suffix, has_chunking=has_chunking))
        write_source_groups(ws, groups)

    if general_groups:
        ws = wb.create_sheet(_sheet_title("General", has_chunking=has_chunking))
        write_source_groups(ws, general_groups)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(output_path)
    return output_path


def build_run_spreadsheet(
    run_dir: Path,
    *,
    output_path: Path | None = None,
    split_aggregate: Path | None = None,
    cost_aggregate: Path | None = None,
) -> Path:
    """Build team_review.xlsx for a single bias run directory.

    Uses the chunking card layout when any trial has ``excerpt_preparation``;
    otherwise the same extractor/consensus cards with non-chunk sheet titles.
    When ``split_aggregate`` / ``cost_aggregate`` are omitted, resolves them from
    ``manifest.derived`` paths written by ``--derive-split`` / ``--derive-cost``.
    """
    run_dir = Path(run_dir)
    records_path = run_dir / "records.jsonl"
    output_path = Path(output_path) if output_path is not None else run_dir / "team_review.xlsx"

    manifest_path = run_dir / "manifest.json"
    manifest = (
        json.loads(manifest_path.read_text())
        if manifest_path.is_file()
        else {}
    )
    derived = manifest.get("derived") or {}
    resolved_split = _resolve_derived_aggregate(
        derived.get("split"),
        override=split_aggregate,
    )
    resolved_cost = _resolve_derived_aggregate(
        derived.get("cost"),
        override=cost_aggregate,
    )
    return build_workbook(
        records_path=records_path,
        output_path=output_path,
        split_aggregate=resolved_split,
        cost_aggregate=resolved_cost,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run-dir",
        type=Path,
        default=None,
        help="Bias run directory (writes <run-dir>/team_review.xlsx by default).",
    )
    parser.add_argument(
        "--records",
        type=Path,
        default=None,
        help="Legacy: path to records.jsonl (defaults under --run-dir when set).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output .xlsx path (default: <run-dir>/team_review.xlsx).",
    )
    parser.add_argument(
        "--split-aggregate",
        type=Path,
        default=None,
        help="Optional split-vs-not aggregate.csv (else from manifest.derived).",
    )
    parser.add_argument(
        "--cost-aggregate",
        type=Path,
        default=None,
        help="Optional cost-benefit aggregate.csv (else from manifest.derived).",
    )
    args = parser.parse_args()
    if args.run_dir is not None:
        path = build_run_spreadsheet(
            args.run_dir,
            output_path=args.output,
            split_aggregate=args.split_aggregate,
            cost_aggregate=args.cost_aggregate,
        )
    else:
        records = args.records or (
            REPO_ROOT
            / "experiments/paper/results/bias-1-vs-3-small"
            / "mixed20_o33_promptmod_chunking"
            / "records.jsonl"
        )
        output = args.output or (
            REPO_ROOT
            / "experiments/paper/results"
            / "chunking_extractor_team_review.xlsx"
        )
        path = build_workbook(
            records_path=records,
            output_path=output,
            split_aggregate=args.split_aggregate,
            cost_aggregate=args.cost_aggregate,
        )
    print(f"wrote {path} ({path.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
