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


def test_runtime_request_shutdown_stops_in_flight_jobs():
    started = threading.Event()
    jobs = [
        JobSpec(job_id="j1", request={"profile": "mtb-h37rv", "locus": "Rv0001"}),
    ]
    source = FakeJobSource(jobs)

    def fake_execute(request, *, job_id=None):
        started.set()
        for _ in range(200):
            if runtime.shutdown_requested:
                raise RuntimeError("shutdown")
            time.sleep(0.01)
        return {"job_id": job_id}

    config = SimpleNamespace(max_slots=1, heartbeat_seconds=1)
    fleet_config = SimpleNamespace(max_slots=1)
    runtime = WorkerRuntime(
        config=config,
        fleet_config=fleet_config,
        job_source=source,
        execute_fn=fake_execute,
    )

    def run_runtime():
        runtime.run()

    thread = threading.Thread(target=run_runtime)
    thread.start()
    assert started.wait(timeout=2)
    runtime.request_shutdown()
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert runtime.shutdown_requested
    assert source.failed or not source.completed


def test_runtime_warns_on_long_running_jobs(monkeypatch, caplog):
    import logging

    caplog.set_level(logging.WARNING)

    class SlowSource(FakeJobSource):
        def __init__(self):
            super().__init__(
                [JobSpec(job_id="j1", request={"profile": "mtb-h37rv", "locus": "Rv0001"})]
            )

        def is_exhausted(self):
            return False

    source = SlowSource()

    def fake_execute(request, *, job_id=None):
        time.sleep(2.0)
        return {"job_id": job_id}

    monkeypatch.setenv("WORKER_STALL_WARN_AFTER_SEC", "0.05")
    monkeypatch.setenv("WORKER_STALL_WARN_INTERVAL_SEC", "0.05")

    config = SimpleNamespace(max_slots=1, heartbeat_seconds=1)
    fleet_config = SimpleNamespace(max_slots=1)
    runtime = WorkerRuntime(
        config=config,
        fleet_config=fleet_config,
        job_source=source,
        execute_fn=fake_execute,
    )

    thread = threading.Thread(target=runtime.run)
    thread.start()
    time.sleep(0.25)
    runtime.request_shutdown()
    thread.join(timeout=5)

    assert any("Still waiting on" in record.message for record in caplog.records)
