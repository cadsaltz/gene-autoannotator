from __future__ import annotations

import argparse
import json
import subprocess
from collections import Counter
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path
from typing import Any

from autoannotation.consensus import (
    DEFAULT_FIELD_SPECS,
    BatchMerger,
    FieldSpec,
    hybrid_section_consensus,
    token_jaccard,
)
from experiments.paper.runners.common import (
    append_jsonl,
    is_nullish,
    load_yaml_config,
    new_run_id,
    stable_json_hash,
    write_aggregate_csv,
    write_json,
)
from experiments.paper.runners.general_consensus import (
    GENERAL_FIELD_SPECS,
    make_biology_batch_merger,
    make_general_batch_merger,
)
from experiments.paper.runners.tiebreak_fixture import (
    case_counts_by_tag,
    filter_cases,
    load_tiebreak_fixture,
    resolve_case_selection,
    validate_case,
)
from experiments.paper.runners.tiebreak_matching import (
    is_invention,
    is_multi_invention,
    match_exact,
    match_soft,
)

PAPER_DIR = Path(__file__).resolve().parents[1]
CONDITIONS = (
    "no_consensus_pick_extractor_0",
    "hybrid_consensus",
)
DRY_SOFT_MATCH = 0.35

# Production normalize_annotation_fields only keeps biology keys. Map general
# multi-field labels onto three string biology slots for the merge, then map back.
GENERAL_MULTI_SLOTS = ("function", "drug_susc_impact", "infection_impact")
BIOLOGY_MULTI_FIELDS = ("function", "drug_susc_impact", "infection_impact")


def _fixture_path(path_value: str) -> Path:
    path = Path(path_value)
    return path if path.is_absolute() else PAPER_DIR / path


def _git_sha() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=PAPER_DIR,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _dry_batch_merger(
    candidates: list[dict[str, Any]],
    unresolved_fields: list[str],
) -> dict[str, Any]:
    """Choose the candidate best supported by a soft-matching peer."""
    result: dict[str, Any] = {}
    for field_key in unresolved_fields:
        values = [
            candidate.get(field_key)
            for candidate in candidates
            if not is_nullish(candidate.get(field_key))
        ]
        if len(values) < 2:
            result[field_key] = None
            continue

        exact_counts = Counter(" ".join(str(value).lower().split()) for value in values)
        exact_winner, exact_count = exact_counts.most_common(1)[0]
        if exact_count >= 2:
            result[field_key] = next(
                value
                for value in values
                if " ".join(str(value).lower().split()) == exact_winner
            )
            continue

        scores = [0.0] * len(values)
        best_pair_score = 0.0
        for left, right in combinations(range(len(values)), 2):
            score = token_jaccard(str(values[left]), str(values[right]))
            scores[left] += score
            scores[right] += score
            best_pair_score = max(best_pair_score, score)
        if best_pair_score < DRY_SOFT_MATCH:
            result[field_key] = None
            continue
        best_index = max(
            range(len(values)),
            key=lambda index: (scores[index], len(str(values[index]))),
        )
        result[field_key] = values[best_index]
    return result


def _make_live_mergers(
    consensus_model: str,
    cache_dir: Path,
) -> dict[str, BatchMerger]:
    from autoannotation import llms

    llm_handler = llms.LlmHandler(cache_dir)
    llm_handler.consensus_model = consensus_model
    return {
        "general": make_general_batch_merger(consensus_model),
        "biology": make_biology_batch_merger(llm_handler),
    }


def _case_records(
    case: dict[str, Any],
    *,
    batch_merger: BatchMerger,
) -> list[dict[str, Any]]:
    if str(case.get("case_family", "")) == "multi_field_mixed":
        return _multi_field_case_records(case, batch_merger=batch_merger)

    field_key = case["field_key"]
    candidates = case["candidates"]
    candidate_values = [candidate.get(field_key) for candidate in candidates]

    baseline_observed = candidates[0].get(field_key)
    baseline = _score_record(
        case,
        condition=CONDITIONS[0],
        observed=baseline_observed,
        provenance="extractor_0",
        llm_invoked=False,
        candidate_values=candidate_values,
    )

    identity = case.get("identity") or {}
    consensus_candidates = candidates
    consensus_field_key = field_key
    fields = DEFAULT_FIELD_SPECS
    if case["domain"] == "general":
        # Production normalization recognizes annotation keys only. Adapt the
        # neutral fixture field through a temporary string slot while retaining
        # the candidate-only general merger.
        consensus_field_key = "function"
        consensus_candidates = [
            {consensus_field_key: candidate.get(field_key)}
            for candidate in candidates
        ]
        fields = (
            FieldSpec(consensus_field_key, GENERAL_FIELD_SPECS[0].kind),
        )
    merged, provenance, llm_calls = hybrid_section_consensus(
        consensus_candidates,
        excerpt=None,
        expected_gene_id=identity.get("gene_id", "GENE1"),
        expected_name=identity.get("name", "gene"),
        fields=fields,
        batch_merger=batch_merger,
    )
    field_provenance = provenance[consensus_field_key]
    hybrid = _score_record(
        case,
        condition=CONDITIONS[1],
        observed=merged.get(consensus_field_key),
        provenance=field_provenance,
        llm_invoked=llm_calls > 0 or field_provenance == "llm_batch_merge",
        candidate_values=candidate_values,
    )
    return [baseline, hybrid]


def _multi_field_case_records(
    case: dict[str, Any],
    *,
    batch_merger: BatchMerger,
) -> list[dict[str, Any]]:
    field_keys = [str(key) for key in case["field_keys"]]
    candidates = case["candidates"]
    expected = case["expected"]
    identity = case.get("identity") or {}

    baseline_observed = {key: candidates[0].get(key) for key in field_keys}
    baseline = _score_record(
        case,
        condition=CONDITIONS[0],
        observed=baseline_observed,
        provenance="extractor_0",
        llm_invoked=False,
        candidate_values=candidates,
        field_keys=field_keys,
    )

    if case["domain"] == "general":
        if len(field_keys) > len(GENERAL_MULTI_SLOTS):
            raise ValueError(
                f"{case['case_id']}: general multi-field supports at most "
                f"{len(GENERAL_MULTI_SLOTS)} fields"
            )
        slot_by_field = {
            field_key: GENERAL_MULTI_SLOTS[index]
            for index, field_key in enumerate(field_keys)
        }
        consensus_candidates = [
            {
                slot_by_field[field_key]: candidate.get(field_key)
                for field_key in field_keys
            }
            for candidate in candidates
        ]
        fields = tuple(
            FieldSpec(slot_by_field[field_key], "string") for field_key in field_keys
        )
    else:
        slot_by_field = {field_key: field_key for field_key in field_keys}
        consensus_candidates = [
            {
                "gene_id": identity.get("gene_id", candidate.get("gene_id", "GENE1")),
                "name": identity.get("name", candidate.get("name", "gene")),
                **{field_key: candidate.get(field_key) for field_key in field_keys},
            }
            for candidate in candidates
        ]
        fields = (
            FieldSpec("gene_id", "identity"),
            FieldSpec("name", "identity"),
            *(FieldSpec(field_key, "string") for field_key in field_keys),
        )

    merged, provenance, llm_calls = hybrid_section_consensus(
        consensus_candidates,
        excerpt=None,
        expected_gene_id=identity.get("gene_id", "GENE1"),
        expected_name=identity.get("name", "gene"),
        fields=fields,
        batch_merger=batch_merger,
    )
    observed = {
        field_key: merged.get(slot_by_field[field_key]) for field_key in field_keys
    }
    field_provenance = {
        field_key: provenance.get(slot_by_field[field_key], "missing")
        for field_key in field_keys
    }
    llm_invoked = llm_calls > 0 or any(
        value == "llm_batch_merge" for value in field_provenance.values()
    )
    hybrid = _score_record(
        case,
        condition=CONDITIONS[1],
        observed=observed,
        provenance=field_provenance,
        llm_invoked=llm_invoked,
        candidate_values=candidates,
        field_keys=field_keys,
    )
    # Keep expected on the record for reviewers (dict).
    hybrid["expected"] = expected
    return [baseline, hybrid]


def _score_record(
    case: dict[str, Any],
    *,
    condition: str,
    observed: Any,
    provenance: Any,
    llm_invoked: bool,
    candidate_values: list[Any],
    field_keys: list[str] | None = None,
) -> dict[str, Any]:
    expected = case.get("expected")
    if field_keys:
        invention = is_multi_invention(observed, candidate_values, field_keys)
        field_key_label = ",".join(field_keys)
    else:
        invention = is_invention(observed, candidate_values)
        field_key_label = case["field_key"]
    return {
        "case_id": case["case_id"],
        "domain": case["domain"],
        "case_family": case["case_family"],
        "field_key": field_key_label,
        "condition": condition,
        "candidates": case["candidates"],
        "expected": expected,
        "observed": observed,
        "llm_invoked": llm_invoked,
        "provenance": provenance,
        "match_exact": match_exact(observed, expected),
        "match_soft": match_soft(observed, expected),
        "invention": invention,
        "expect_llm": bool(case["expect_llm"]),
        "expect_llm_matched": llm_invoked == bool(case["expect_llm"]),
    }


def _rate(records: list[dict[str, Any]], key: str) -> float:
    return (
        sum(bool(record[key]) for record in records) / len(records)
        if records
        else 0.0
    )


def _aggregate_row(
    records: list[dict[str, Any]],
    *,
    scope: str,
    value: str,
) -> dict[str, Any]:
    baseline = [record for record in records if record["condition"] == CONDITIONS[0]]
    consensus = [record for record in records if record["condition"] == CONDITIONS[1]]
    necessity_baseline = [record for record in baseline if not record["match_soft"]]
    necessity_ids = {record["case_id"] for record in necessity_baseline}
    necessity_consensus = [
        record for record in consensus if record["case_id"] in necessity_ids
    ]
    nonsense_consensus = [
        record
        for record in consensus
        if "nonsense" in record["case_family"]
    ]
    return {
        "scope": scope,
        "value": value,
        "case_count": len(consensus),
        "consensus_match_exact_rate": _rate(consensus, "match_exact"),
        "consensus_match_soft_rate": _rate(consensus, "match_soft"),
        "baseline_match_exact_rate": _rate(baseline, "match_exact"),
        "baseline_match_soft_rate": _rate(baseline, "match_soft"),
        "necessity_case_count": len(necessity_ids),
        "necessity_delta": (
            _rate(necessity_consensus, "match_soft")
            - _rate(necessity_baseline, "match_soft")
        ),
        "llm_invoked_rate": _rate(consensus, "llm_invoked"),
        "expect_llm_calibration_rate": _rate(consensus, "expect_llm_matched"),
        "invention_rate": _rate(consensus, "invention"),
        "nonsense_majority_adoption_rate": _rate(
            nonsense_consensus,
            "match_soft",
        ),
    }


def _aggregate_rows(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = [_aggregate_row(records, scope="overall", value="all")]
    for key in ("domain", "case_family", "expect_llm"):
        values = sorted({str(record[key]) for record in records})
        for value in values:
            subset = [
                record for record in records if str(record[key]) == value
            ]
            rows.append(_aggregate_row(subset, scope=key, value=value))
    return rows


def run_experiment(
    *,
    config_path: Path,
    run_id: str | None = None,
    dry_run: bool = False,
    limit: int | None = None,
    results_root: Path | None = None,
) -> Path:
    config_path = Path(config_path)
    config = load_yaml_config(config_path)
    experiment_id = config.get("experiment_id")
    if experiment_id not in {
        "tiebreak-consensus",
        "tiebreak-nonsense",
        "tiebreak-non-nonsense",
    }:
        raise ValueError(f"unsupported tie-break experiment_id: {experiment_id!r}")
    if tuple(config.get("conditions") or ()) != CONDITIONS:
        raise ValueError(f"conditions must be exactly {CONDITIONS!r}")

    consensus_model = (config.get("models") or {}).get("consensus")
    if not consensus_model:
        raise ValueError("models.consensus is required")
    fixture_path = _fixture_path((config.get("fixtures") or {})["constructed"])
    fixture_document = json.loads(fixture_path.read_text())
    include_tags, match_any = resolve_case_selection(config)
    cases = filter_cases(
        load_tiebreak_fixture(fixture_path),
        include_tags,
        match_any=match_any,
    )
    invalid = [
        error
        for case in cases
        for error in validate_case(case)
    ]
    if invalid:
        raise ValueError("invalid tie-break fixture cases: " + "; ".join(invalid))
    if limit is not None:
        if limit < 1:
            raise ValueError("limit must be at least 1")
        cases = cases[:limit]
    if not cases:
        raise ValueError("config filter selected no tie-break cases")

    run_id = run_id or new_run_id()
    root = Path(results_root) if results_root is not None else PAPER_DIR / "results"
    output_dir = root / experiment_id / run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    records_path = output_dir / "records.jsonl"
    records_path.write_text("")

    manifest = {
        "experiment_id": experiment_id,
        "run_id": run_id,
        "dry_run": dry_run,
        "git_sha": _git_sha(),
        "config_path": str(config_path),
        "config_hash": stable_json_hash(config),
        "fixture_path": str(fixture_path),
        "fixture_hash": stable_json_hash(fixture_document),
        "case_count": len(cases),
        "case_selection": {
            "include_tags": include_tags,
            "match_any": match_any,
        },
        "case_counts_by_tag": case_counts_by_tag(cases),
        "conditions": list(CONDITIONS),
        "model_tags": {"consensus": consensus_model},
        "excerpt_policy": "always_none",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    write_json(output_dir / "manifest.json", manifest)

    live_mergers = (
        None
        if dry_run
        else _make_live_mergers(consensus_model, output_dir / "_llm_cache")
    )
    records: list[dict[str, Any]] = []
    for case in cases:
        merger = _dry_batch_merger if dry_run else live_mergers[case["domain"]]
        for record in _case_records(case, batch_merger=merger):
            records.append(record)
            append_jsonl(records_path, record)
    write_aggregate_csv(output_dir / "aggregate.csv", _aggregate_rows(records))
    return output_dir


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run constructed tie-break consensus experiments.",
    )
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--run-id")
    parser.add_argument("--limit", type=int)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    output_dir = run_experiment(
        config_path=args.config,
        run_id=args.run_id,
        dry_run=args.dry_run,
        limit=args.limit,
    )
    print(output_dir)


if __name__ == "__main__":
    main()
