"""Largest-first residency packing and mode selection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
import os

ResidencyMode = Literal["single", "cache", "warm_stack"]

DEFAULT_PACK_FACTOR = 0.70
PACK_FACTOR_ENV = "WORKER_RESIDENCY_PACK_FACTOR"

GiB = 1024**3


def pack_factor_from_env(default: float = DEFAULT_PACK_FACTOR) -> float:
    raw = (os.getenv(PACK_FACTOR_ENV) or "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    if value <= 0:
        return default
    return min(value, 1.0)


def pack_budget_bytes(cache_budget_bytes: int, *, factor: float = DEFAULT_PACK_FACTOR) -> int:
    if cache_budget_bytes <= 0 or factor <= 0:
        return 0
    return int(cache_budget_bytes * min(factor, 1.0))


def pack_models_largest_first(
    model_sizes: dict[str, int],
    budget_bytes: int,
) -> list[str]:
    """Pack a prefix of models sorted by descending size.

    Walk largest → smallest and stop at the first model that does not fit.
    (Do not skip over a too-large model to squeeze a smaller one in.)
    """
    if budget_bytes <= 0 or not model_sizes:
        return []
    ordered = sorted(model_sizes.items(), key=lambda item: (-item[1], item[0]))
    packed: list[str] = []
    used = 0
    for name, size in ordered:
        if size <= 0:
            continue
        if used + size > budget_bytes:
            break
        packed.append(name)
        used += size
    return packed


@dataclass(frozen=True)
class ResidencyPlan:
    mode: ResidencyMode
    packed_models: list[str]
    max_loaded: int
    pack_budget_bytes: int
    cache_budget_bytes: int
    pack_factor: float

    @property
    def use_model_cache(self) -> bool:
        return self.mode == "cache"

    @property
    def should_prewarm(self) -> bool:
        return self.mode == "warm_stack"


def select_residency_mode(
    model_sizes: dict[str, int],
    *,
    cache_budget_bytes: int,
    pack_factor: float = DEFAULT_PACK_FACTOR,
) -> ResidencyPlan:
    budget = pack_budget_bytes(cache_budget_bytes, factor=pack_factor)
    packed = pack_models_largest_first(model_sizes, budget)
    n_required = len(model_sizes)
    n_packed = len(packed)

    if n_required == 0 or n_packed <= 1:
        mode: ResidencyMode = "single"
        max_loaded = 1
    elif n_packed < n_required:
        mode = "cache"
        max_loaded = max(1, n_packed)
    else:
        mode = "warm_stack"
        max_loaded = max(1, n_required)

    return ResidencyPlan(
        mode=mode,
        packed_models=packed,
        max_loaded=max_loaded,
        pack_budget_bytes=budget,
        cache_budget_bytes=cache_budget_bytes,
        pack_factor=pack_factor,
    )
