import threading

from shared.job_progress import JobProgressEvent
from worker.progress_reporter import ProgressReporter


class FakeClient:
    def __init__(self, calls):
        self._calls = calls

    def progress(self, job_id, current_step, **fields):
        self._calls.append({"job_id": job_id, "current_step": current_step, **fields})


class FlakyClient:
    """Raises on `progress()` calls while `failing` is True; otherwise records them."""

    def __init__(self, calls):
        self._calls = calls
        self.failing = True

    def progress(self, job_id, current_step, **fields):
        if self.failing:
            raise RuntimeError("PATCH /jobs/{id}/progress failed")
        self._calls.append({"job_id": job_id, "current_step": current_step, **fields})


class BlockingClient:
    """Blocks inside `progress()` (per job_id) until released, to prove the
    reporter's lock isn't held across the network call."""

    def __init__(self, calls, job_ids):
        self._calls = calls
        self.entered = {job_id: threading.Event() for job_id in job_ids}
        self.release = threading.Event()

    def progress(self, job_id, current_step, **fields):
        self.entered[job_id].set()
        self.release.wait(timeout=5)
        self._calls.append({"job_id": job_id, "current_step": current_step, **fields})


def test_progress_reporter_debounces_same_phase():
    calls = []
    client = FakeClient(calls)
    reporter = ProgressReporter(client, debounce_sec=10.0)
    event = JobProgressEvent(phase="extracting", sections_done=1, sections_total=10, pass_name="target")
    reporter.report("j1", event)
    event2 = event.model_copy(update={"sections_done": 2})
    reporter.report("j1", event2)
    assert len(calls) == 1
    reporter.flush("j1")
    assert calls[-1]["sections_done"] == 2


def test_progress_reporter_sends_immediately_on_phase_change():
    calls = []
    client = FakeClient(calls)
    reporter = ProgressReporter(client, debounce_sec=10.0)
    event = JobProgressEvent(phase="fetching", sections_done=0, sections_total=None, pass_name="target")
    reporter.report("j1", event)
    event2 = JobProgressEvent(phase="extracting", sections_done=0, sections_total=5, pass_name="target")
    reporter.report("j1", event2)
    assert len(calls) == 2
    assert calls[-1]["phase"] == "extracting"


def test_progress_reporter_first_event_sent_immediately():
    calls = []
    client = FakeClient(calls)
    reporter = ProgressReporter(client, debounce_sec=10.0)
    event = JobProgressEvent(phase="fetching", sections_done=0, sections_total=None)
    reporter.report("j1", event)
    assert len(calls) == 1
    assert calls[0]["job_id"] == "j1"
    assert calls[0]["current_step"] == "fetching ?/? sections" or "fetching" in calls[0]["current_step"]


def test_progress_reporter_flush_is_noop_when_nothing_pending():
    calls = []
    client = FakeClient(calls)
    reporter = ProgressReporter(client, debounce_sec=10.0)
    event = JobProgressEvent(phase="fetching", sections_done=0, sections_total=None)
    reporter.report("j1", event)
    assert len(calls) == 1
    reporter.flush("j1")
    assert len(calls) == 1
    reporter.flush("unknown-job")
    assert len(calls) == 1


def test_progress_reporter_sends_again_after_debounce_window_elapses():
    calls = []
    client = FakeClient(calls)
    reporter = ProgressReporter(client, debounce_sec=0.01)
    event = JobProgressEvent(phase="extracting", sections_done=1, sections_total=10)
    reporter.report("j1", event)
    assert len(calls) == 1

    import time

    time.sleep(0.02)
    event2 = event.model_copy(update={"sections_done": 2})
    reporter.report("j1", event2)
    assert len(calls) == 2
    assert calls[-1]["sections_done"] == 2


def test_progress_reporter_close_flushes_all_pending_jobs():
    calls = []
    client = FakeClient(calls)
    reporter = ProgressReporter(client, debounce_sec=10.0)
    event_a = JobProgressEvent(phase="extracting", sections_done=1, sections_total=10)
    event_b = JobProgressEvent(phase="extracting", sections_done=1, sections_total=10)
    reporter.report("a", event_a)
    reporter.report("b", event_b)
    assert len(calls) == 2

    reporter.report("a", event_a.model_copy(update={"sections_done": 3}))
    reporter.report("b", event_b.model_copy(update={"sections_done": 4}))
    assert len(calls) == 2

    reporter.close()
    assert len(calls) == 4
    by_job = {c["job_id"]: c["sections_done"] for c in calls[-2:]}
    assert by_job == {"a": 3, "b": 4}


def test_progress_reporter_debounce_sec_from_env(monkeypatch):
    monkeypatch.setenv("WORKER_PROGRESS_DEBOUNCE_SEC", "0.01")
    calls = []
    client = FakeClient(calls)
    reporter = ProgressReporter(client)
    assert reporter._debounce_sec == 0.01


def test_progress_reporter_report_does_not_raise_when_client_fails():
    calls = []
    client = FlakyClient(calls)
    reporter = ProgressReporter(client, debounce_sec=10.0)
    event = JobProgressEvent(phase="fetching", sections_done=0, sections_total=None)
    reporter.report("j1", event)  # should not raise
    assert calls == []


def test_progress_reporter_flush_does_not_raise_when_client_fails():
    calls = []
    client = FlakyClient(calls)
    reporter = ProgressReporter(client, debounce_sec=10.0)
    event = JobProgressEvent(phase="extracting", sections_done=1, sections_total=10)
    reporter.report("j1", event)
    assert calls == []
    reporter.flush("j1")  # should not raise
    assert calls == []


def test_progress_reporter_retries_failed_send_on_next_flush():
    calls = []
    client = FlakyClient(calls)
    reporter = ProgressReporter(client, debounce_sec=10.0)
    event = JobProgressEvent(phase="fetching", sections_done=0, sections_total=None)
    reporter.report("j1", event)
    assert calls == []

    client.failing = False
    reporter.flush("j1")
    assert len(calls) == 1
    assert calls[0]["job_id"] == "j1"


def test_progress_reporter_retries_failed_send_on_next_report_after_debounce():
    calls = []
    client = FlakyClient(calls)
    reporter = ProgressReporter(client, debounce_sec=0.01)
    event = JobProgressEvent(phase="extracting", sections_done=1, sections_total=10)
    reporter.report("j1", event)  # first event, send fails, stays pending
    assert calls == []

    client.failing = False
    import time

    time.sleep(0.02)
    event2 = event.model_copy(update={"sections_done": 2})
    reporter.report("j1", event2)
    assert len(calls) == 1
    assert calls[0]["sections_done"] == 2


def test_progress_reporter_send_happens_outside_lock():
    calls = []
    client = BlockingClient(calls, job_ids=["job-a", "job-b"])
    reporter = ProgressReporter(client, debounce_sec=10.0)

    t = threading.Thread(
        target=reporter.report,
        args=("job-a", JobProgressEvent(phase="fetching", sections_done=0, sections_total=None)),
    )
    t.start()
    assert client.entered["job-a"].wait(timeout=5)

    # While job-a's send is blocked inside client.progress(), job-b's report()
    # must be able to reach client.progress() too — proving the reporter's
    # lock was released before the (slow) network call, not held across it.
    t2 = threading.Thread(
        target=reporter.report,
        args=("job-b", JobProgressEvent(phase="fetching", sections_done=0, sections_total=None)),
    )
    t2.start()
    assert client.entered["job-b"].wait(timeout=5)

    client.release.set()
    t.join(timeout=5)
    t2.join(timeout=5)
    assert len(calls) == 2
