from __future__ import annotations

import time
from dataclasses import dataclass

from worker.fleet.config import FleetConfig


def _percentile(values: list[int], pct: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * (pct / 100.0)
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    weight = rank - low
    return int(ordered[low] * (1 - weight) + ordered[high] * weight)


def _peak_in_flight(calls: list[CallRecord]) -> int:
    if not calls:
        return 0
    events: list[tuple[float, int]] = []
    for call in calls:
        start = call.ts
        end = call.ts + (call.total_ms / 1000.0)
        events.append((start, 1))
        events.append((end, -1))
    events.sort(key=lambda item: (item[0], -item[1]))
    peak = 0
    current = 0
    for _ts, delta in events:
        current += delta
        peak = max(peak, current)
    return peak


@dataclass
class CallRecord:
    ts: float
    job_id: str | None
    role: str
    model: str
    backend: str
    queue_wait_ms: int
    inference_ms: int
    total_ms: int
    success: bool


@dataclass
class JobRecord:
    wall_ms: int
    failed: bool


class MetricsCollector:
    def __init__(self) -> None:
        self._batch_start: float | None = None
        self._batch_end: float | None = None
        self._calls: list[CallRecord] = []
        self._jobs: dict[str, JobRecord] = {}

    def begin_batch(self) -> None:
        self._batch_start = time.monotonic()
        self._batch_end = None
        self._calls.clear()
        self._jobs.clear()

    def record_call(
        self,
        *,
        model: str,
        role: str,
        backend: str,
        queue_wait_ms: int,
        inference_ms: int,
        total_ms: int,
        job_id: str | None,
        success: bool,
    ) -> None:
        now = time.monotonic()
        call_start = now - (total_ms / 1000.0)
        self._calls.append(
            CallRecord(
                ts=call_start,
                job_id=job_id,
                role=role,
                model=model,
                backend=backend,
                queue_wait_ms=queue_wait_ms,
                inference_ms=inference_ms,
                total_ms=total_ms,
                success=success,
            )
        )

    def record_job_done(self, job_id: str, *, wall_ms: int, failed: bool = False) -> None:
        self._jobs[job_id] = JobRecord(wall_ms=wall_ms, failed=failed)

    def end_batch(self) -> None:
        self._batch_end = time.monotonic()

    def build_report(
        self,
        *,
        fleet_cfg: FleetConfig,
        jobs_submitted: int,
        model_mode: str,
    ) -> dict:
        makespan_sec = self._makespan_sec()
        jobs_completed = sum(1 for job in self._jobs.values() if not job.failed)
        jobs_failed = sum(1 for job in self._jobs.values() if job.failed)
        jobs_per_hour = 0.0
        if makespan_sec > 0:
            jobs_per_hour = jobs_completed / (makespan_sec / 3600.0)

        per_model = self._per_model_stats(makespan_sec)
        per_job = self._per_job_stats()

        return {
            "primary_kpi": "jobs_per_hour",
            "batch": {
                "jobs_submitted": jobs_submitted,
                "jobs_completed": jobs_completed,
                "jobs_failed": jobs_failed,
                "makespan_sec": round(makespan_sec, 3),
                "jobs_per_hour": round(jobs_per_hour, 1),
            },
            "fleet": {
                "num_servers": fleet_cfg.num_servers,
                "parallel": fleet_cfg.parallel,
                "lanes": fleet_cfg.agg_lanes,
                "model_mode": model_mode,
            },
            "per_model": per_model,
            "per_job": per_job,
            "efficiency": {"score": 0.0, "components": {}},
        }

    def _makespan_sec(self) -> float:
        if self._batch_start is None:
            return 0.0
        end = self._batch_end if self._batch_end is not None else time.monotonic()
        return max(0.0, end - self._batch_start)

    def _per_model_stats(self, makespan_sec: float) -> dict[str, dict]:
        by_model: dict[str, list[CallRecord]] = {}
        for call in self._calls:
            by_model.setdefault(call.model, []).append(call)

        stats: dict[str, dict] = {}
        for model, calls in by_model.items():
            queue_waits = [call.queue_wait_ms for call in calls]
            calls_per_sec = 0.0
            if makespan_sec > 0:
                calls_per_sec = len(calls) / makespan_sec
            stats[model] = {
                "calls": len(calls),
                "calls_per_sec": round(calls_per_sec, 3),
                "peak_in_flight": _peak_in_flight(calls),
                "p50_queue_wait_ms": _percentile(queue_waits, 50),
                "p95_queue_wait_ms": _percentile(queue_waits, 95),
                "p99_queue_wait_ms": _percentile(queue_waits, 99),
            }
        return stats

    def _per_job_stats(self) -> dict[str, dict]:
        stall_by_job: dict[str, int] = {}
        for call in self._calls:
            if call.job_id is None:
                continue
            stall_by_job[call.job_id] = stall_by_job.get(call.job_id, 0) + call.queue_wait_ms

        stats: dict[str, dict] = {}
        for job_id, job in self._jobs.items():
            stats[job_id] = {
                "wall_ms": job.wall_ms,
                "stall_ms": stall_by_job.get(job_id, 0),
            }
        return stats
