from __future__ import annotations

from typing import Any

from autoannotation.consensus import token_jaccard, _string_traceable_to_candidates
from experiments.paper.runners.common import is_nullish, field_values_equal

SOFT_JACCARD = 0.50


def match_exact(observed: Any, expected: Any) -> bool:
    if isinstance(expected, dict) or isinstance(observed, dict):
        if not isinstance(expected, dict) or not isinstance(observed, dict):
            return False
        if set(expected.keys()) != set(observed.keys()):
            return False
        return all(match_exact(observed[key], expected[key]) for key in expected)
    if is_nullish(observed) and is_nullish(expected):
        return True
    if is_nullish(observed) or is_nullish(expected):
        return False
    return " ".join(str(observed).lower().split()) == " ".join(str(expected).lower().split())


def match_soft(observed: Any, expected: Any, *, kind: str = "string") -> bool:
    if isinstance(expected, dict) or isinstance(observed, dict):
        if not isinstance(expected, dict) or not isinstance(observed, dict):
            return False
        if set(expected.keys()) != set(observed.keys()):
            return False
        return all(match_soft(observed[key], expected[key]) for key in expected)
    if kind in {"boolean", "array"}:
        return field_values_equal(observed, expected, kind=kind)
    if is_nullish(observed) and is_nullish(expected):
        return True
    if is_nullish(observed) or is_nullish(expected):
        return False
    return token_jaccard(str(observed), str(expected)) >= SOFT_JACCARD


def is_invention(observed: Any, candidate_values: list[Any]) -> bool:
    if isinstance(observed, dict):
        # Multi-field: invent if any scored field invents relative to that field's
        # candidate values (caller should pass parallel dicts or flat values).
        return False
    if is_nullish(observed):
        return False
    return not _string_traceable_to_candidates(
        str(observed), [str(value) for value in candidate_values]
    )


def is_multi_invention(
    observed: dict[str, Any],
    candidates: list[dict[str, Any]],
    field_keys: list[str],
) -> bool:
    return any(
        is_invention(
            observed.get(field_key),
            [candidate.get(field_key) for candidate in candidates],
        )
        for field_key in field_keys
    )
