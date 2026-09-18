from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable
from typing import Any

from worker.client import BackendClient
from worker.runtime import JobSpec, JobSource

log = logging.getLogger(__name__)

_EMPTY_CLAIM_LOG_INTERVAL_SEC = 30.0


def _claim_poll_seconds() -> float:
    raw = os.getenv("WORKER_CLAIM_POLL_SECONDS", "1.0").strip()
    try:
        value = float(raw)
    except ValueError:
        return 1.0
    return max(0.25, value)


class BackendJobSource(JobSource):
    def __init__(
        self,
        client: BackendClient,
        free_slots_fn: Callable[[], int],
        *,
        poll_seconds: float | None = None,
        active_jobs_fn: Callable[[], int] | None = None,
    ) -> None:
        self._client = client
        self._free_slots = free_slots_fn
        self._active_jobs_fn = active_jobs_fn or (lambda: 0)
        self._poll_seconds = _claim_poll_seconds() if poll_seconds is None else poll_seconds
        self._last_empty_claim_log_at = 0.0

    def claim_one(self) -> JobSpec | None:
        free_slots = self._free_slots()
        if free_slots <= 0:
            return None
        try:
            claim = self._client.claim(free_slots)
        except Exception as exc:  # noqa: BLE001 - keep serve loop alive across WAN blips
            # BackendClient already retries transient httpx errors; if we still
            # fail (NAT drop, Pi restart), sleep via wait_or_sleep and try again.
            log.warning("Claim failed; will retry after poll interval: %s", exc)
            return None
        if claim is None:
            self._maybe_log_empty_claim(free_slots)
            return None
        log.info("Claimed job %s from backend", claim["job_id"])
        return JobSpec(job_id=claim["job_id"], request=dict(claim["request"]))
    def _maybe_log_empty_claim(self, free_slots: int) -> None:
        active_jobs = self._active_jobs_fn()
        if active_jobs > 0:
            # Expected while a job runs but spare slots remain — not an error.
            return
        now = time.monotonic()
        if now - self._last_empty_claim_log_at < _EMPTY_CLAIM_LOG_INTERVAL_SEC:
            return
        self._last_empty_claim_log_at = now
        log.info(
            "Idle: no job in backend queue (local free_slots=%s). "
            "Submit jobs via POST /jobs or check GET /workers for stale workers.",
            free_slots,
        )

    def on_complete(self, job_id: str, result: Any) -> None:
        self._client.complete(job_id, result)

    def on_fail(self, job_id: str, error: str, retryable: bool) -> None:
        self._client.fail(job_id, error, retryable)

    def is_exhausted(self) -> bool:
        # Backend-backed workers serve continuously until externally drained.
        return False

    def wait_or_sleep(self, timeout: float) -> None:
        del timeout  # Backend polling uses its own interval.
        time.sleep(self._poll_seconds)
