from __future__ import annotations

import inspect
import logging
import os
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Protocol

from worker import executor

PERMANENT_ERROR_MARKERS = ("locus_schema_mismatch", "profile or organism", "name or locus")

log = logging.getLogger(__name__)

STALL_WARN_AFTER_SEC = 120.0
STALL_WARN_INTERVAL_SEC = 60.0


def _float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        return float(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class JobSpec:
    job_id: str
    request: dict[str, Any]


class JobSource(Protocol):
    def claim_one(self) -> JobSpec | None: ...

    def on_complete(self, job_id: str, result: Any) -> None: ...

    def on_fail(self, job_id: str, error: str, retryable: bool) -> None: ...

    def is_exhausted(self) -> bool: ...

    def wait_or_sleep(self, timeout: float) -> None: ...


@dataclass
class ActiveJob:
    job_id: str
    future: Future[Any]
    started_at: float


def _supports_job_id(execute_fn: Any) -> bool:
    try:
        sig = inspect.signature(execute_fn)
    except (TypeError, ValueError):
        return True
    for param in sig.parameters.values():
        if param.kind == inspect.Parameter.VAR_KEYWORD:
            return True
    job_id_param = sig.parameters.get("job_id")
    if job_id_param is None:
        return False
    return job_id_param.kind in (
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
        inspect.Parameter.KEYWORD_ONLY,
    )


def _is_retryable(error_message: str) -> bool:
    return not any(marker in error_message for marker in PERMANENT_ERROR_MARKERS)


class WorkerRuntime:
    def __init__(
        self,
        *,
        config,
        fleet_config,
        job_source: JobSource,
        execute_fn,
        heartbeat_fn=None,
        collect_metrics: bool = False,
        metrics_collector=None,
    ) -> None:
        self._config = config
        self._fleet_config = fleet_config
        self._job_source = job_source
        self._execute_fn = execute_fn
        self._heartbeat_fn = heartbeat_fn
        self._collect_metrics = collect_metrics
        self._metrics_collector = metrics_collector

        self._max_slots = int(getattr(fleet_config, "max_slots", getattr(config, "max_slots", 0)))
        self._heartbeat_seconds = float(getattr(config, "heartbeat_seconds", 15))
        if self._heartbeat_seconds <= 0:
            self._heartbeat_seconds = 15.0

        self._pool = ThreadPoolExecutor(max_workers=max(1, self._max_slots))
        self._active_jobs: dict[str, ActiveJob] = {}

        self._heartbeat_stop = threading.Event()
        self._heartbeat_thread: threading.Thread | None = None
        self._shutdown_requested = threading.Event()

        self._execute_supports_job_id = _supports_job_id(execute_fn)

        self._stall_warn_after_sec = _float_env(
            "WORKER_STALL_WARN_AFTER_SEC",
            STALL_WARN_AFTER_SEC,
        )
        self._stall_warn_interval_sec = _float_env(
            "WORKER_STALL_WARN_INTERVAL_SEC",
            STALL_WARN_INTERVAL_SEC,
        )
        self._last_stall_warn_at = 0.0

    @property
    def active_jobs(self) -> dict[str, ActiveJob]:
        return self._active_jobs

    @property
    def shutdown_requested(self) -> bool:
        return self._shutdown_requested.is_set()

    def free_slots(self) -> int:
        return max(0, self._max_slots - len(self._active_jobs))

    def request_shutdown(self) -> None:
        self._shutdown_requested.set()
        executor.terminate_active_jobs()

    def run(self) -> dict[str, Any] | None:
        self._start_heartbeat_thread()
        self._emit_heartbeat()
        if self._collect_metrics:
            self._metrics_begin()
        try:
            while not self._done():
                if self._shutdown_requested.is_set():
                    executor.terminate_active_jobs()
                self._reap_finished()
                if not self._shutdown_requested.is_set():
                    self._claim_to_capacity()
                self._maybe_warn_stalled_jobs()
                if self._done():
                    break
                self._job_source.wait_or_sleep(timeout=0.1)
            self._reap_finished()
            return self._maybe_build_report()
        finally:
            if self._collect_metrics:
                self._metrics_end()
            self._stop_heartbeat_thread()
            if self._shutdown_requested.is_set():
                executor.terminate_active_jobs()
                self._pool.shutdown(wait=False, cancel_futures=True)
            else:
                self._pool.shutdown(wait=True)

    def _done(self) -> bool:
        if self._active_jobs:
            return False
        if self._shutdown_requested.is_set():
            return True
        return self._job_source.is_exhausted()

    def _claim_to_capacity(self) -> None:
        while self.free_slots() > 0:
            job = self._job_source.claim_one()
            if job is None:
                return
            self._start_job(job)

    def _start_job(self, job: JobSpec) -> None:
        locus = job.request.get("locus") or job.request.get("name") or "?"
        log.info("Started job %s (locus=%s)", job.job_id, locus)
        future = self._pool.submit(self._execute, job)
        self._active_jobs[job.job_id] = ActiveJob(
            job_id=job.job_id,
            future=future,
            started_at=time.monotonic(),
        )

    def _execute(self, job: JobSpec) -> Any:
        if self._execute_supports_job_id:
            return self._execute_fn(job.request, job_id=job.job_id)
        return self._execute_fn(job.request)

    def _reap_finished(self) -> None:
        finished: list[tuple[str, Future[Any]]] = []
        for job_id, active in self._active_jobs.items():
            if active.future.done():
                finished.append((job_id, active.future))

        for job_id, future in finished:
            active = self._active_jobs.pop(job_id, None)
            wall_ms = 0
            if active is not None:
                wall_ms = max(0, int((time.monotonic() - active.started_at) * 1000))
            try:
                result = future.result()
            except Exception as exc:  # noqa: BLE001 - report all execution errors.
                error = str(exc)
                log.warning("Failed job %s after %dms: %s", job_id, wall_ms, error)
                self._job_source.on_fail(job_id, error, _is_retryable(error))
                self._metrics_record_job_done(job_id, wall_ms=wall_ms, failed=True)
            else:
                log.info("Completed job %s in %dms", job_id, wall_ms)
                self._job_source.on_complete(job_id, result)
                self._metrics_record_job_done(job_id, wall_ms=wall_ms, failed=False)

    def _maybe_warn_stalled_jobs(self) -> None:
        if not self._active_jobs:
            return
        now = time.monotonic()
        if now - self._last_stall_warn_at < self._stall_warn_interval_sec:
            return

        stalled: list[tuple[str, int]] = []
        for job_id, active in self._active_jobs.items():
            elapsed_sec = max(0, int(now - active.started_at))
            if elapsed_sec >= self._stall_warn_after_sec:
                stalled.append((job_id, elapsed_sec))

        if not stalled:
            return

        self._last_stall_warn_at = now
        summary = ", ".join(f"{job_id} ({elapsed}s)" for job_id, elapsed in stalled)
        log.warning(
            "Still waiting on %d job(s): %s. Check router dispatch/chat logs. "
            "If Ollama vanished from top, look for 'Ollama server ... exited unexpectedly'.",
            len(stalled),
            summary,
        )

    def _start_heartbeat_thread(self) -> None:
        if self._heartbeat_fn is None:
            return
        if self._heartbeat_thread is not None:
            return

        def _loop() -> None:
            while not self._heartbeat_stop.wait(self._heartbeat_seconds):
                self._emit_heartbeat()

        self._heartbeat_thread = threading.Thread(
            target=_loop,
            name="worker-runtime-heartbeat",
            daemon=True,
        )
        self._heartbeat_thread.start()

    def _stop_heartbeat_thread(self) -> None:
        self._heartbeat_stop.set()
        if self._heartbeat_thread is not None:
            self._heartbeat_thread.join(timeout=5)

    def _emit_heartbeat(self) -> None:
        if self._heartbeat_fn is None:
            return
        try:
            self._heartbeat_fn(active_jobs=len(self._active_jobs), free_slots=self.free_slots())
        except Exception:
            # Runtime should continue processing jobs if heartbeat fails.
            return

    def _metrics_begin(self) -> None:
        if self._metrics_collector is None:
            return
        self._metrics_collector.begin_batch()

    def _metrics_end(self) -> None:
        if self._metrics_collector is None:
            return
        self._metrics_collector.end_batch()

    def _metrics_record_job_done(self, job_id: str, *, wall_ms: int, failed: bool) -> None:
        if not self._collect_metrics:
            return
        if self._metrics_collector is None:
            return
        self._metrics_collector.record_job_done(job_id, wall_ms=wall_ms, failed=failed)

    def _maybe_build_report(self) -> dict[str, Any] | None:
        build_report = getattr(self._job_source, "build_report", None)
        if callable(build_report):
            return build_report()
        return None

