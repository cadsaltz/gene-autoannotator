from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from worker.client import CoordinatorClient
from worker.config import load_config
from worker.progress_reporter import ProgressReporter
from worker.runtime import JobSpec, WorkerRuntime
from worker.runtime import execute_annotation_job as _execute_job


class _OneShotJobSource:
    def __init__(
        self,
        client: CoordinatorClient,
        job: JobSpec,
        reporter: ProgressReporter,
    ) -> None:
        self._client = client
        self._job = job
        self._reporter = reporter
        self.failed = False
        self._finished = False

    def claim_one(self) -> JobSpec | None:
        job, self._job = self._job, None
        return job

    def on_complete(self, job_id: str, result: Any) -> None:
        self._reporter.flush(job_id)
        self._client.complete(job_id, result)
        self._finished = True

    def on_fail(self, job_id: str, error: str, retryable: bool) -> None:
        self._reporter.flush(job_id)
        self._client.fail(job_id, error, retryable)
        self.failed = True
        self._finished = True

    def is_exhausted(self) -> bool:
        return self._finished

    def wait_or_sleep(self, timeout: float) -> None:
        time.sleep(timeout)


def _job_from_file(path: str) -> JobSpec:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return JobSpec(job_id=str(payload["job_id"]), request=dict(payload["request"]))


def _make_execute_fn(reporter: ProgressReporter):
    def execute(request_dict: dict[str, Any], *, job_id=None, on_progress=None):
        def combined_progress(event) -> None:
            reporter.report(job_id, event)
            if on_progress is not None:
                on_progress(event)

        return _execute_job(request_dict, job_id=job_id, on_progress=combined_progress)

    return execute


def main(args: argparse.Namespace) -> int:
    config = load_config()
    client = CoordinatorClient(config)

    if getattr(args, "claim_one", False):
        client.register()
        claim = client.claim(1)
        if claim is None:
            return 0
        job = JobSpec(job_id=str(claim["job_id"]), request=dict(claim["request"]))
    else:
        job = _job_from_file(args.job_file)

    reporter = ProgressReporter(client)
    source = _OneShotJobSource(client, job, reporter)
    runtime_config = SimpleNamespace(max_slots=1, heartbeat_seconds=config.heartbeat_seconds)
    runtime = WorkerRuntime(
        config=runtime_config,
        fleet_config=runtime_config,
        job_source=source,
        execute_fn=_make_execute_fn(reporter),
    )
    runtime.run()
    return 1 if source.failed else 0
