from __future__ import annotations

import json
from itertools import combinations
from pathlib import Path
from typing import Any, Iterable

from autoannotation.consensus import token_jaccard
from experiments.paper.runners.tiebreak_matching import match_exact, match_soft

PARAPHRASE_JACCARD = 0.35


def _extractor_zero_is_minority(case: dict[str, Any]) -> bool:
    agreement = case.get("agreement")
    if isinstance(agreement, dict) and agreement.get("extractor_0_is_minority") is True:
        return True
    notes = str(case.get("notes", "")).lower()
    return "extractor 0" in notes and any(
        term in notes for term in ("minority", "conflict", "wrong")
    )


def _majority_candidate_values(
    values: list[Any],
    expected: Any,
    *,
    extractor_zero_is_minority: bool,
) -> list[Any]:
    """Return the non-minority candidate values for paraphrase validation."""
    if extractor_zero_is_minority:
        return values[1:]

    soft_matches = [value for value in values if match_soft(value, expected)]
    if len(soft_matches) >= 2:
        return soft_matches

    # Fall back to agreement shape: one minority, two majority — drop lowest
    # token_jaccard to expected when soft-match does not identify both majors.
    minority_index = min(
        range(len(values)),
        key=lambda index: token_jaccard(str(values[index]), str(expected)),
    )
    return [value for index, value in enumerate(values) if index != minority_index]


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


def _field_keys_for_case(case: dict[str, Any]) -> list[str]:
    raw = case.get("field_keys")
    if isinstance(raw, list) and raw:
        return [str(key) for key in raw]
    field_key = case.get("field_key")
    return [str(field_key)] if field_key is not None else []


def validate_case(case: dict[str, Any]) -> list[str]:
    """Return all structural and agreement errors for one constructed case."""
    errors: list[str] = []
    case_id = case.get("case_id", "<unknown>")
    candidates = case.get("candidates")
    field_keys = _field_keys_for_case(case)
    family = str(case.get("case_family", ""))

    if not isinstance(candidates, list) or len(candidates) != 3:
        errors.append(f"{case_id}: expected exactly 3 candidates")

    if not field_keys:
        errors.append(f"{case_id}: missing field_key or field_keys")
        return errors

    candidate_items = candidates if isinstance(candidates, list) else []

    if family == "multi_field_mixed":
        expected = case.get("expected")
        if not isinstance(expected, dict):
            errors.append(f"{case_id}: multi_field_mixed expected must be an object")
            return errors
        if set(expected.keys()) != set(field_keys):
            errors.append(
                f"{case_id}: expected keys must match field_keys {field_keys!r}"
            )
        for index, candidate in enumerate(candidate_items):
            if not isinstance(candidate, dict):
                errors.append(f"{case_id}: candidate {index} must be an object")
                continue
            for field_key in field_keys:
                if field_key not in candidate:
                    errors.append(
                        f"{case_id}: candidate {index} missing field_key {field_key!r}"
                    )
        return errors

    field_key = field_keys[0]
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
        majority_values = _majority_candidate_values(
            values,
            expected,
            extractor_zero_is_minority=_extractor_zero_is_minority(case),
        )
        if len(majority_values) < 2 or not any(
            token_jaccard(str(left), str(right)) >= PARAPHRASE_JACCARD
            for left, right in combinations(majority_values, 2)
        ):
            errors.append(
                f"{case_id}: paraphrase family requires a majority candidate pair "
                f"with token_jaccard >= {PARAPHRASE_JACCARD}"
            )

    if (
        _extractor_zero_is_minority(case)
        and match_soft(values[0], expected)
    ):
        errors.append(
            f"{case_id}: extractor_0 minority must not soft-match expected"
        )

    return errors
