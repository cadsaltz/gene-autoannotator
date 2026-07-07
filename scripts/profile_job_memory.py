#!/usr/bin/env python3
"""Observe host memory while a real coordinator annotation job runs."""

from __future__ import annotations

import re
import statistics
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

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


def preflight(coordinator_url: str, token: str) -> dict:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    with httpx.Client(base_url=coordinator_url, headers=headers, timeout=30.0) as client:
        health = client.get("/health").json()
        if health.get("status") != "ok":
            raise RuntimeError(f"Coordinator unhealthy: {health}")
        workers = health.get("workers", {})
        if workers.get("connected", 0) < 1:
            raise RuntimeError("No workers connected; start a worker before profiling.")
        if workers.get("total_slots", 0) < 1:
            raise RuntimeError("Workers have 0 slots; increase ANNOTATION_MEMORY_BUDGET_GB.")
        annotations = health.get("stores", {}).get("annotations", {})
        if annotations.get("status") not in ("ok", "available"):
            raise RuntimeError(
                "Mongo annotation store unavailable; set MONGO_URI on the coordinator."
            )
        return health


def submit_job(client: httpx.Client, *, profile: str, locus: str) -> str:
    payload = {
        "profile": profile,
        "locus": locus,
        "allow_online_name_lookup": False,
        "allow_ortholog_fallback": True,
    }
    resp = client.post("/jobs", json=payload)
    resp.raise_for_status()
    return resp.json()["id"]


def poll_job(client: httpx.Client, job_id: str, poll_interval: float = 10.0) -> dict:
    while True:
        job = client.get(f"/jobs/{job_id}").json()
        status = job.get("status")
        if status in ("completed", "failed"):
            return job
        time.sleep(poll_interval)


def verify_annotation_saved(client: httpx.Client, profile: str, locus: str) -> dict | None:
    annotation_id = f"{profile}:{locus}"
    resp = client.get(f"/annotations/{annotation_id}")
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.json()
