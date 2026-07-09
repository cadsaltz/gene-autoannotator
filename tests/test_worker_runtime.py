import threading
import time
from types import SimpleNamespace

from worker.runtime import JobSpec, WorkerRuntime


class FakeJobSource:
    def __init__(self, jobs):
        self._jobs = list(jobs)
        self.completed = []
        self.failed = []

    def claim_one(self):
        if not self._jobs:
            return None
        return self._jobs.pop(0)

    def on_complete(self, job_id, result):
        self.completed.append((job_id, result))

    def on_fail(self, job_id, error, retryable):
        self.failed.append((job_id, error, retryable))

    def is_exhausted(self):
        return not self._jobs

    def wait_or_sleep(self, timeout):
        time.sleep(min(timeout, 0.01))


def test_runtime_runs_up_to_max_slots_concurrently():
    jobs = [
        JobSpec(job_id="j1", request={"profile": "mtb-h37rv", "locus": "Rv0001"}),
        JobSpec(job_id="j2", request={"profile": "mtb-h37rv", "locus": "Rv0002"}),
        JobSpec(job_id="j3", request={"profile": "mtb-h37rv", "locus": "Rv0003"}),
        JobSpec(job_id="j4", request={"profile": "mtb-h37rv", "locus": "Rv0004"}),
    ]
    source = FakeJobSource(jobs)

    lock = threading.Lock()
    current = 0
    peak = 0

    def fake_execute(request, *, job_id=None):
        nonlocal current, peak
        with lock:
            current += 1
            peak = max(peak, current)
        time.sleep(0.05)
        with lock:
            current -= 1
        return {"job_id": job_id, "locus": request["locus"]}

    config = SimpleNamespace(max_slots=2, heartbeat_seconds=1)
    fleet_config = SimpleNamespace(max_slots=2)
    runtime = WorkerRuntime(
        config=config,
        fleet_config=fleet_config,
        job_source=source,
        execute_fn=fake_execute,
    )

    report = runtime.run()

    assert report is None
    assert peak == 2
    assert len(source.completed) == 4
    assert source.failed == []
