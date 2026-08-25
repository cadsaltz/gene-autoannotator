from __future__ import annotations

from typing import Any

from experiments.paper.runners.common import field_values_equal, is_nullish


def classify_extractor_split(values_by_extractor: dict[str, Any], *, kind: str) -> str:
    non_null = [v for v in values_by_extractor.values() if not is_nullish(v)]
    if len(non_null) == 0:
        return 'unanimous'
    if len(non_null) == 1:
        return 'partial'
    # cluster distinct values
    distinct = []
    for v in non_null:
        if not any(field_values_equal(v, d, kind=kind) for d in distinct):
            distinct.append(v)
    if len(distinct) >= 2:
        return 'split'
    return 'unanimous'
