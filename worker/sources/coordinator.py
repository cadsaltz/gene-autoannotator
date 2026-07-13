from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable
from typing import Any

from worker.client import CoordinatorClient
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


class CoordinatorJobSource(JobSource):
    def __init__(
        self,
        client: CoordinatorClient,
        free_slots_fn: Callable[[], int],
        *,
        poll_seconds: float | None = None,
    ) -> None:
        self._client = client
        self._free_slots = free_slots_fn
        self._poll_seconds = _claim_poll_seconds() if poll_seconds is None else poll_seconds
        self._last_empty_claim_log_at = 0.0

    def claim_one(self) -> JobSpec | None:
        free_slots = self._free_slots()
        if free_slots <= 0:
            return None
        claim = self._client.claim(free_slots)
        if claim is None:
            self._maybe_log_empty_claim(free_slots)
            return None
        log.info("Claimed job %s from coordinator", claim["job_id"])
        return JobSpec(job_id=claim["job_id"], request=dict(claim["request"]))

    def _maybe_log_empty_claim(self, free_slots: int) -> None:
        now = time.monotonic()
        if now - self._last_empty_claim_log_at < _EMPTY_CLAIM_LOG_INTERVAL_SEC:
            return
        self._last_empty_claim_log_at = now
        log.info(
            "No job claimed (coordinator returned 204) with local free_slots=%s. "
            "If jobs are queued, check coordinator GET /workers for stale workers "
            "with higher free_slots, or confirm the job status is queued.",
            free_slots,
        )

    def on_complete(self, job_id: str, result: Any) -> None:
        self._client.complete(job_id, result)

    def on_fail(self, job_id: str, error: str, retryable: bool) -> None:
        self._client.fail(job_id, error, retryable)

    def is_exhausted(self) -> bool:
        # Coordinator-backed workers serve continuously until externally drained.
        return False

    def wait_or_sleep(self, timeout: float) -> None:
        del timeout  # Coordinator polling uses its own interval.
        time.sleep(self._poll_seconds)
