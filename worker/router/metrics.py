from __future__ import annotations

import time
from dataclasses import dataclass

from worker.fleet.config import FleetConfig, MemoryTier

# Reference throughput for normalizing jobs/hour into a 0–1 component (~8.5 jph/lane
# matches observed nano/performance single-GPU benches).
JPH_PER_LANE_REFERENCE = 8.0

MEMORY_TIER_SCORES: dict[MemoryTier, float] = {
    "warm_stack": 1.0,
    "swap": 0.85,
    "vram_overflow": 0.65,
}

EFFICIENCY_WEIGHTS = {
    "lane_utilization": 0.35,
    "throughput": 0.30,
    "memory_tier": 0.15,
    "job_success_rate": 0.10,
    "queue_responsiveness": 0.10,
}


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
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


@dataclass
class JobRecord:
    wall_ms: int
    failed: bool


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


def _integrate_lane_occupancy(
    calls: list[CallRecord],
    *,
    parallel: int,
    window_start: float,
    window_end: float,
) -> tuple[float, float, int]:
    """Return (busy_lane_sec, idle_lane_sec, peak_in_flight) for one backend."""
    if window_end <= window_start or parallel <= 0:
        return 0.0, 0.0, 0

    events: list[tuple[float, int]] = []
    for call in calls:
        start = max(call.ts, window_start)
        end = min(call.ts + (call.total_ms / 1000.0), window_end)
        if end <= start:
            continue
        events.append((start, 1))
        events.append((end, -1))
    events.sort(key=lambda item: (item[0], -item[1]))

    peak = 0
    current = 0
    busy_sec = 0.0
    prev = window_start
    for event_time, delta in events:
        if event_time > window_end:
            break
        segment_end = min(event_time, window_end)
        segment = segment_end - prev
        if segment > 0:
            busy_sec += min(current, parallel) * segment
        current += delta
        peak = max(peak, min(current, parallel))
        prev = segment_end
    if prev < window_end:
        busy_sec += min(current, parallel) * (window_end - prev)

    capacity_sec = parallel * (window_end - window_start)
    idle_sec = max(0.0, capacity_sec - busy_sec)
    return busy_sec, idle_sec, peak


def _fleet_peak_lane_usage(
    calls_by_backend: dict[str, list[CallRecord]],
    *,
    parallel_by_backend: dict[str, int],
    window_start: float,
    window_end: float,
) -> int:
    """Maximum sum of in-flight calls across all backends at any instant."""
    if window_end <= window_start:
        return 0

    events: list[tuple[float, str, int]] = []
    for backend, calls in calls_by_backend.items():
        for call in calls:
            start = max(call.ts, window_start)
            end = min(call.ts + (call.total_ms / 1000.0), window_end)
            if end <= start:
                continue
            events.append((start, backend, 1))
            events.append((end, backend, -1))
    events.sort(key=lambda item: (item[0], -item[2]))

    in_flight_by_backend: dict[str, int] = {backend: 0 for backend in parallel_by_backend}
    peak_total = 0
    for event_time, backend, delta in events:
        if event_time > window_end:
            break
        in_flight_by_backend[backend] = in_flight_by_backend.get(backend, 0) + delta
        total = sum(
            min(count, parallel_by_backend.get(host, 0))
            for host, count in in_flight_by_backend.items()
        )
        peak_total = max(peak_total, total)
    return peak_total


def _queue_responsiveness_score(calls: list[CallRecord]) -> float:
    if not calls:
        return 1.0
    waits = [call.queue_wait_ms for call in calls]
    p95 = _percentile(waits, 95)
    # 5s p95 queue wait → ~0.5; 0ms → 1.0
    return 1.0 / (1.0 + (p95 / 5000.0))


def tokens_from_ollama_result(result: dict) -> tuple[int | None, int | None, int | None]:
    """Extract prompt/output token counts from an Ollama chat response."""

    def _int_value(key: str) -> int | None:
        value = result.get(key)
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    input_tokens = _int_value("prompt_eval_count")
    output_tokens = _int_value("eval_count")
    total_tokens = None
    if input_tokens is not None and output_tokens is not None:
        total_tokens = input_tokens + output_tokens
    return input_tokens, output_tokens, total_tokens


def _empty_token_bucket() -> dict:
    return {
        "calls": 0,
        "calls_with_tokens": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
    }


def _add_tokens_to_bucket(bucket: dict, call: CallRecord) -> None:
    bucket["calls"] += 1
    if call.input_tokens is None and call.output_tokens is None:
        return
    bucket["calls_with_tokens"] += 1
    bucket["input_tokens"] += call.input_tokens or 0
    bucket["output_tokens"] += call.output_tokens or 0
    if call.total_tokens is not None:
        bucket["total_tokens"] += call.total_tokens
    elif call.input_tokens is not None and call.output_tokens is not None:
        bucket["total_tokens"] += call.input_tokens + call.output_tokens


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
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        total_tokens: int | None = None,
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
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
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

        per_backend = self._per_backend_stats(fleet_cfg, makespan_sec)
        per_model = self._per_model_stats(makespan_sec)
        per_job = self._per_job_stats()
        efficiency = self._efficiency_stats(
            fleet_cfg=fleet_cfg,
            jobs_submitted=jobs_submitted,
            jobs_completed=jobs_completed,
            jobs_per_hour=jobs_per_hour,
            per_backend=per_backend,
        )
        token_usage = self._token_usage_stats()

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
                "memory_tier": fleet_cfg.memory_tier,
                "keep_alive": fleet_cfg.keep_alive,
                "w_all_gb": round(fleet_cfg.w_all_bytes / (1024**3), 2),
                "w_peak_gb": round(
                    (fleet_cfg.w_peak_bytes or fleet_cfg.w_all_bytes) / (1024**3),
                    2,
                ),
            },
            "per_backend": per_backend,
            "per_model": per_model,
            "per_job": per_job,
            "token_usage": token_usage,
            "efficiency": efficiency,
        }

    def _makespan_sec(self) -> float:
        if self._batch_start is None:
            return 0.0
        end = self._batch_end if self._batch_end is not None else time.monotonic()
        return max(0.0, end - self._batch_start)

    def _measurement_window(self) -> tuple[float, float]:
        start = self._batch_start if self._batch_start is not None else time.monotonic()
        end = self._batch_end if self._batch_end is not None else time.monotonic()
        return start, end

    def _calls_by_backend(self) -> dict[str, list[CallRecord]]:
        grouped: dict[str, list[CallRecord]] = {}
        for call in self._calls:
            grouped.setdefault(call.backend, []).append(call)
        return grouped

    def _per_backend_stats(self, fleet_cfg: FleetConfig, makespan_sec: float) -> dict[str, dict]:
        window_start, window_end = self._measurement_window()
        hosts = fleet_cfg.backend_hosts()
        calls_by_backend = self._calls_by_backend()
        parallel_by_backend = {
            host: fleet_cfg.parallel for host in hosts
        }
        for backend in calls_by_backend:
            parallel_by_backend.setdefault(backend, fleet_cfg.parallel)

        stats: dict[str, dict] = {}
        total_busy = 0.0
        total_idle = 0.0
        total_capacity = 0.0
        for host in hosts:
            calls = calls_by_backend.get(host, [])
            busy_sec, idle_sec, peak = _integrate_lane_occupancy(
                calls,
                parallel=fleet_cfg.parallel,
                window_start=window_start,
                window_end=window_end,
            )
            capacity_sec = fleet_cfg.parallel * makespan_sec
            utilization = (busy_sec / capacity_sec) if capacity_sec > 0 else 0.0
            inference_ms = sum(call.inference_ms for call in calls)
            queue_wait_ms = sum(call.queue_wait_ms for call in calls)
            stats[host] = {
                "parallel": fleet_cfg.parallel,
                "calls": len(calls),
                "busy_lane_sec": round(busy_sec, 3),
                "idle_lane_sec": round(idle_sec, 3),
                "lane_capacity_sec": round(capacity_sec, 3),
                "lane_utilization": round(utilization, 4),
                "peak_in_flight": peak,
                "inference_ms_total": inference_ms,
                "queue_wait_ms_total": queue_wait_ms,
            }
            total_busy += busy_sec
            total_idle += idle_sec
            total_capacity += capacity_sec

        peak_lane_usage = _fleet_peak_lane_usage(
            calls_by_backend,
            parallel_by_backend=parallel_by_backend,
            window_start=window_start,
            window_end=window_end,
        )
        fleet_utilization = (total_busy / total_capacity) if total_capacity > 0 else 0.0
        stats["_fleet"] = {
            "lanes": fleet_cfg.agg_lanes,
            "busy_lane_sec": round(total_busy, 3),
            "idle_lane_sec": round(total_idle, 3),
            "lane_capacity_sec": round(total_capacity, 3),
            "lane_utilization": round(fleet_utilization, 4),
            "peak_lane_usage": peak_lane_usage,
            "burst_lane_capacity": fleet_cfg.agg_lanes,
        }
        return stats

    def _per_model_stats(self, makespan_sec: float) -> dict[str, dict]:
        by_model: dict[str, list[CallRecord]] = {}
        for call in self._calls:
            by_model.setdefault(call.model, []).append(call)

        stats: dict[str, dict] = {}
        for model, calls in by_model.items():
            queue_waits = [call.queue_wait_ms for call in calls]
            inference_ms = sum(call.inference_ms for call in calls)
            queue_wait_ms = sum(call.queue_wait_ms for call in calls)
            active_ms = inference_ms + queue_wait_ms
            calls_per_sec = 0.0
            if makespan_sec > 0:
                calls_per_sec = len(calls) / makespan_sec
            stats[model] = {
                "calls": len(calls),
                "calls_per_sec": round(calls_per_sec, 3),
                "peak_in_flight": _peak_in_flight(calls),
                "inference_ms_total": inference_ms,
                "queue_wait_ms_total": queue_wait_ms,
                "active_ms_total": active_ms,
                "inference_fraction": round(
                    inference_ms / active_ms, 4,
                ) if active_ms > 0 else 0.0,
                "p50_queue_wait_ms": _percentile(queue_waits, 50),
                "p95_queue_wait_ms": _percentile(queue_waits, 95),
                "p99_queue_wait_ms": _percentile(queue_waits, 99),
            }
        return stats

    def _per_job_stats(self) -> dict[str, dict]:
        stall_by_job: dict[str, int] = {}
        inference_by_job: dict[str, int] = {}
        for call in self._calls:
            if call.job_id is None:
                continue
            stall_by_job[call.job_id] = stall_by_job.get(call.job_id, 0) + call.queue_wait_ms
            inference_by_job[call.job_id] = (
                inference_by_job.get(call.job_id, 0) + call.inference_ms
            )

        stats: dict[str, dict] = {}
        for job_id, job in self._jobs.items():
            stall_ms = stall_by_job.get(job_id, 0)
            inference_ms = inference_by_job.get(job_id, 0)
            stats[job_id] = {
                "wall_ms": job.wall_ms,
                "stall_ms": stall_ms,
                "inference_ms": inference_ms,
                "non_llm_ms": max(0, job.wall_ms - inference_ms - stall_ms),
            }
        return stats

    def _token_usage_stats(self) -> dict:
        total = _empty_token_bucket()
        per_model: dict[str, dict] = {}

        for call in self._calls:
            if not call.success:
                continue
            _add_tokens_to_bucket(total, call)
            bucket = per_model.setdefault(call.model, _empty_token_bucket())
            _add_tokens_to_bucket(bucket, call)

        return {
            "total": total,
            "per_model": dict(sorted(per_model.items())),
            "notes": [
                "Informational only; token counts depend on papers/sections analyzed.",
                "Not used in efficiency score or jobs_per_hour.",
            ],
        }

    def _efficiency_stats(
        self,
        *,
        fleet_cfg: FleetConfig,
        jobs_submitted: int,
        jobs_completed: int,
        jobs_per_hour: float,
        per_backend: dict[str, dict],
    ) -> dict:
        fleet_summary = per_backend.get("_fleet", {})
        lane_utilization = float(fleet_summary.get("lane_utilization", 0.0))

        lanes = max(1, fleet_cfg.agg_lanes)
        throughput_per_lane = jobs_per_hour / lanes if lanes else 0.0
        throughput = min(1.0, throughput_per_lane / JPH_PER_LANE_REFERENCE)

        memory_tier = fleet_cfg.memory_tier
        memory_score = MEMORY_TIER_SCORES.get(memory_tier, 0.75)

        success_rate = (
            jobs_completed / jobs_submitted if jobs_submitted > 0 else 0.0
        )
        queue_responsiveness = _queue_responsiveness_score(self._calls)

        components = {
            "lane_utilization": round(lane_utilization, 4),
            "throughput": round(throughput, 4),
            "memory_tier": round(memory_score, 4),
            "job_success_rate": round(success_rate, 4),
            "queue_responsiveness": round(queue_responsiveness, 4),
        }
        weighted = sum(
            components[key] * EFFICIENCY_WEIGHTS[key] for key in EFFICIENCY_WEIGHTS
        )
        score = round(weighted * 100.0, 1)

        return {
            "score": score,
            "components": components,
            "weights": dict(EFFICIENCY_WEIGHTS),
            "derived": {
                "jobs_per_hour_per_lane": round(throughput_per_lane, 2),
                "reference_jph_per_lane": JPH_PER_LANE_REFERENCE,
                "peak_lane_usage": fleet_summary.get("peak_lane_usage", 0),
                "burst_lane_capacity": fleet_summary.get("burst_lane_capacity", lanes),
                "idle_lane_sec": fleet_summary.get("idle_lane_sec", 0.0),
                "busy_lane_sec": fleet_summary.get("busy_lane_sec", 0.0),
            },
            "notes": [
                "Score is 0–100 from weighted lane utilization, throughput per lane, "
                "memory tier fit, job success rate, and queue responsiveness.",
                "Lane idle time is capacity_sec − busy_lane_sec across all backends; "
                "busy time is integrated in-flight occupancy capped by parallel.",
                "peak_lane_usage is burst concurrency (max sum of in-flight calls fleet-wide).",
            ],
        }
