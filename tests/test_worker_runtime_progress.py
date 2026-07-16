import threading
import time
from types import SimpleNamespace

from shared.job_progress import JobProgressEvent
from worker.runtime import JobSpec, WorkerRuntime


class FakeJobSource:
    def __init__(self, jobs, *, jobs_submitted=None):
        self._jobs = list(jobs)
        self.jobs_submitted = jobs_submitted if jobs_submitted is not None else len(jobs)
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


def _runtime(source, execute_fn):
    config = SimpleNamespace(max_slots=1, heartbeat_seconds=1)
    fleet_config = SimpleNamespace(max_slots=1)
    return WorkerRuntime(
        config=config,
        fleet_config=fleet_config,
        job_source=source,
        execute_fn=execute_fn,
    )


def test_runtime_stores_progress_for_active_job():
    release = threading.Event()
    job_started = threading.Event()
    job = JobSpec(job_id="j1", request={"profile": "mtb-h37rv", "locus": "Rv0001"})
    source = FakeJobSource([job])

    def fake_execute(request, *, job_id=None, on_progress=None):
        job_started.set()
        release.wait(timeout=2)
        return {"job_id": job_id}

    runtime = _runtime(source, fake_execute)
    thread = threading.Thread(target=runtime.run)
    thread.start()
    assert job_started.wait(timeout=2)

    event = JobProgressEvent(
        phase="extracting",
        sections_done=2,
        sections_total=9,
        pass_name="target",
    )
    runtime._on_job_progress("j1", event)

    snap = runtime.snapshot()
    assert len(snap["active"]) == 1
    active = snap["active"][0]
    assert active["job_id"] == "j1"
    assert active["locus"] == "Rv0001"
    assert active["progress"]["phase"] == "extracting"
    assert active["progress"]["sections_done"] == 2
    assert active["progress"]["sections_total"] == 9
    assert snap["jobs_completed"] == 0
    assert snap["jobs_failed"] == 0
    assert snap["jobs_total"] == 1

    release.set()
    thread.join(timeout=5)
    assert not thread.is_alive()

    final = runtime.snapshot()
    assert final["jobs_completed"] == 1
    assert final["jobs_failed"] == 0
    assert final["active"] == []


def test_runtime_wires_on_progress_into_execute_fn():
    progress_seen = threading.Event()
    job = JobSpec(job_id="j1", request={"profile": "mtb-h37rv", "locus": "Rv0002"})
    source = FakeJobSource([job])

    def fake_execute(request, *, job_id=None, on_progress=None):
        assert on_progress is not None
        on_progress(
            JobProgressEvent(
                phase="fetching",
                sections_done=0,
                sections_total=4,
                pass_name="target",
            )
        )
        progress_seen.set()
        return {"job_id": job_id}

    runtime = _runtime(source, fake_execute)
    runtime.run()

    assert progress_seen.is_set()
    assert runtime.active_jobs == {}


def test_runtime_tracks_failed_jobs_in_snapshot():
    job = JobSpec(job_id="j1", request={"profile": "mtb-h37rv", "locus": "Rv0003"})
    source = FakeJobSource([job], jobs_submitted=3)

    def fake_execute(request, *, job_id=None, on_progress=None):
        raise RuntimeError("boom")

    runtime = _runtime(source, fake_execute)
    runtime.run()

    snap = runtime.snapshot()
    assert snap["jobs_completed"] == 0
    assert snap["jobs_failed"] == 1
    assert snap["jobs_total"] == 3
    assert snap["active"] == []
