#!/usr/bin/env python3
"""Observe host memory while a real coordinator annotation job runs."""

from __future__ import annotations

import statistics
from typing import Any

GIB = 1024 ** 3
DEFAULT_SAFETY_FACTOR = 0.20


def parse_free_b_mem_line(line: str) -> dict[str, int] | None:
    """Parse the Mem: row from `free -b` output."""
    if not line.strip().startswith("Mem:"):
        return None
    parts = line.split()
    if len(parts) < 7:
        return None
    return {
        "total_bytes": int(parts[1]),
        "used_bytes": int(parts[2]),
        "free_bytes": int(parts[3]),
        "shared_bytes": int(parts[4]),
        "buff_cache_bytes": int(parts[5]),
        "available_bytes": int(parts[6]),
    }


def percentile(values: list[int], pct: float) -> int:
    if not values:
        raise ValueError("empty values")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * (pct / 100.0)
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    weight = rank - low
    return int(ordered[low] * (1 - weight) + ordered[high] * weight)


def summarize_bytes(values: list[int]) -> dict[str, int | float]:
    return {
        "min": min(values),
        "max": max(values),
        "mean": int(statistics.mean(values)),
        "stdev": int(statistics.pstdev(values)) if len(values) > 1 else 0,
        "p50": percentile(values, 50),
        "p95": percentile(values, 95),
        "p99": percentile(values, 99),
    }


def recommend_job_memory_gb(peak_incremental_bytes: int, *, safety_factor: float) -> int:
    raw_gb = (peak_incremental_bytes * (1.0 + safety_factor)) / GIB
    return int(-(-raw_gb // 1))  # ceil to whole GB
