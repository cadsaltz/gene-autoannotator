from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from shared.job_contract import AnnotationJobRequest
from worker.runtime import JobSpec, JobSource


class BatchJobSource(JobSource):
    def __init__(self, jobs_path: str | Path) -> None:
        self._jobs = self._load_jobs(jobs_path)
        self._next_idx = 0
        self._pending: set[str] = set()
        self.completed: dict[str, Any] = {}
        self.failed: dict[str, dict[str, Any]] = {}

    @property
    def jobs_submitted(self) -> int:
        return len(self._jobs)

    def claim_one(self) -> JobSpec | None:
        if self._next_idx >= len(self._jobs):
            return None
        job = self._jobs[self._next_idx]
        self._next_idx += 1
        self._pending.add(job.job_id)
        return job

    def on_complete(self, job_id: str, result: Any) -> None:
        self._pending.discard(job_id)
        self.completed[job_id] = result

    def on_fail(self, job_id: str, error: str, retryable: bool) -> None:
        self._pending.discard(job_id)
        self.failed[job_id] = {"error": error, "retryable": retryable}

    def is_exhausted(self) -> bool:
        return self._next_idx >= len(self._jobs) and not self._pending

    def wait_or_sleep(self, timeout: float) -> None:
        time.sleep(min(timeout, 0.05))

    @staticmethod
    def _load_jobs(jobs_path: str | Path) -> list[JobSpec]:
        path = Path(jobs_path)
        specs: list[JobSpec] = []
        with path.open(encoding="utf-8") as handle:
            for idx, line in enumerate(handle, start=1):
                payload = line.strip()
                if not payload:
                    continue
                request = AnnotationJobRequest(**json.loads(payload))
                specs.append(
                    JobSpec(
                        job_id=f"bench-{idx:03d}",
                        request=request.model_dump(mode="json"),
                    )
                )
        return specs
