#!/usr/bin/env python3
"""Observe host memory while a real coordinator annotation job runs."""

from __future__ import annotations

import re
import statistics
import subprocess
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

GIB = 1024 ** 3
DEFAULT_SAFETY_FACTOR = 0.20


@dataclass
class MemoryLogSampler:
    log_path: Path
    interval_sec: float = 2.0
    _thread: threading.Thread | None = None
    _stop: threading.Event | None = None

    def start(self) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._stop = threading.Event()

        def _loop() -> None:
            with self.log_path.open("a", encoding="utf-8") as fh:
                while not self._stop.is_set():
                    ts = datetime.now(timezone.utc).isoformat()
                    fh.write(f"\n=== {ts} ===\n")
                    fh.flush()
                    for cmd in (["free", "-b"], ["free", "-h"]):
                        try:
                            out = subprocess.check_output(cmd, text=True, stderr=subprocess.STDOUT)
                        except (OSError, subprocess.CalledProcessError) as exc:
                            out = f"<error running {cmd}: {exc}>\n"
                        fh.write(out)
                        if not out.endswith("\n"):
                            fh.write("\n")
                        fh.flush()
                    self._stop.wait(self.interval_sec)

        self._thread = threading.Thread(target=_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._stop is not None:
            self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self.interval_sec + 5)


def parse_memory_log(log_path: Path) -> list[dict[str, Any]]:
    text = log_path.read_text(encoding="utf-8")
    parts = re.split(r"\n=== (.+?) ===\n", text)
    samples: list[dict[str, Any]] = []
    for i in range(1, len(parts), 2):
        timestamp = parts[i]
        block = parts[i + 1]
        for line in block.splitlines():
            if line.strip().startswith("Mem:"):
                parsed = parse_free_b_mem_line(line)
                if parsed is not None:
                    samples.append({"timestamp": timestamp, **parsed})
                break
    return samples


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
