from __future__ import annotations

from typing import Any

from autoannotation.consensus import token_jaccard, _string_traceable_to_candidates
from experiments.paper.runners.common import is_nullish, field_values_equal

SOFT_JACCARD = 0.50


def match_exact(observed: Any, expected: Any) -> bool:
    if is_nullish(observed) and is_nullish(expected):
        return True
    if is_nullish(observed) or is_nullish(expected):
        return False
    return " ".join(str(observed).lower().split()) == " ".join(str(expected).lower().split())


def match_soft(observed: Any, expected: Any, *, kind: str = "string") -> bool:
    if kind in {"boolean", "array"}:
        return field_values_equal(observed, expected, kind=kind)
    if is_nullish(observed) and is_nullish(expected):
        return True
    if is_nullish(observed) or is_nullish(expected):
        return False
    return token_jaccard(str(observed), str(expected)) >= SOFT_JACCARD


def is_invention(observed: Any, candidate_values: list[str]) -> bool:
    if is_nullish(observed):
        return False
    return not _string_traceable_to_candidates(str(observed), [str(v) for v in candidate_values])
