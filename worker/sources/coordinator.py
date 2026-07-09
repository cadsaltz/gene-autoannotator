from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from worker.client import CoordinatorClient
from worker.runtime import JobSpec, JobSource


class CoordinatorJobSource(JobSource):
    def __init__(
        self,
        client: CoordinatorClient,
        free_slots_fn: Callable[[], int],
        *,
        poll_seconds: float = 1.0,
    ) -> None:
        self._client = client
        self._free_slots = free_slots_fn
        self._poll_seconds = poll_seconds

    def claim_one(self) -> JobSpec | None:
        free_slots = self._free_slots()
        if free_slots <= 0:
            return None
        claim = self._client.claim(free_slots)
        if claim is None:
            return None
        return JobSpec(job_id=claim["job_id"], request=dict(claim["request"]))

    def on_complete(self, job_id: str, result: Any) -> None:
        self._client.complete(job_id, result)

    def on_fail(self, job_id: str, error: str, retryable: bool) -> None:
        self._client.fail(job_id, error, retryable)

    def is_exhausted(self) -> bool:
        # Coordinator-backed workers serve continuously until externally drained.
        return False

    def wait_or_sleep(self, timeout: float) -> None:
        time.sleep(min(timeout, self._poll_seconds))
