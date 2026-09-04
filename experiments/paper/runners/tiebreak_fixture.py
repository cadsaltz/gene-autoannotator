from __future__ import annotations

import json
from itertools import combinations
from pathlib import Path
from typing import Any, Iterable

from autoannotation.consensus import token_jaccard
from experiments.paper.runners.tiebreak_matching import match_exact, match_soft


def load_tiebreak_fixture(path: str | Path) -> list[dict[str, Any]]:
    """Load the item list from a versioned tie-break fixture."""
    with Path(path).open(encoding="utf-8") as handle:
        fixture = json.load(handle)

    items = fixture.get("items") if isinstance(fixture, dict) else None
    if not isinstance(items, list):
        raise ValueError("tie-break fixture must contain an 'items' list")
    if not all(isinstance(item, dict) for item in items):
        raise ValueError("every tie-break fixture item must be an object")
    return items


def filter_cases(
    items: Iterable[dict[str, Any]],
    experiment_tags: Iterable[str],
) -> list[dict[str, Any]]:
    """Return cases containing every requested experiment tag."""
    requested = set(experiment_tags)
    return [
        item
        for item in items
        if requested.issubset(set(item.get("experiment_tags", [])))
    ]


def validate_case(case: dict[str, Any]) -> list[str]:
    """Return all structural and agreement errors for one constructed case."""
    errors: list[str] = []
    case_id = case.get("case_id", "<unknown>")
    candidates = case.get("candidates")
    field_key = case.get("field_key")

    if not isinstance(candidates, list) or len(candidates) != 3:
        errors.append(f"{case_id}: expected exactly 3 candidates")

    candidate_items = candidates if isinstance(candidates, list) else []
    values: list[Any] = []
    for index, candidate in enumerate(candidate_items):
        if not isinstance(candidate, dict) or field_key not in candidate:
            errors.append(
                f"{case_id}: candidate {index} missing field_key {field_key!r}"
            )
            continue
        values.append(candidate[field_key])

    if len(candidate_items) != 3 or len(values) != 3:
        return errors

    expected = case.get("expected")
    family = str(case.get("case_family", ""))
    expect_llm = case.get("expect_llm")

    if expected is None:
        if any(match_exact(left, right) for left, right in combinations(values, 2)):
            errors.append(
                f"{case_id}: null-expected candidates must be mutually non-matching"
            )
        return errors

    exact_expected_count = sum(match_exact(value, expected) for value in values)
    if expect_llm is False and family.startswith("exact_"):
        if exact_expected_count < 2:
            errors.append(
                f"{case_id}: exact family requires at least 2 candidates "
                "matching expected"
            )

    if expect_llm is True and family.startswith("paraphrase_"):
        if exact_expected_count >= 2:
            errors.append(
                f"{case_id}: paraphrase family would create a deterministic "
                "exact majority"
            )
        if not any(
            token_jaccard(str(left), str(right)) >= 0.35
            for left, right in combinations(values, 2)
        ):
            errors.append(
                f"{case_id}: paraphrase family requires a candidate pair "
                "with token_jaccard >= 0.35"
            )

    agreement = case.get("agreement")
    extractor_zero_is_minority = (
        isinstance(agreement, dict)
        and agreement.get("extractor_0_is_minority") is True
    )
    notes = str(case.get("notes", "")).lower()
    notes_require_minority = (
        "extractor 0" in notes
        and any(term in notes for term in ("minority", "conflict", "wrong"))
    )
    if (
        (extractor_zero_is_minority or notes_require_minority)
        and match_soft(values[0], expected)
    ):
        errors.append(
            f"{case_id}: extractor_0 minority must not soft-match expected"
        )

    return errors
