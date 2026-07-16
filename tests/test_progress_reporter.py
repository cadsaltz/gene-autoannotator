from shared.job_progress import JobProgressEvent
from worker.progress_reporter import ProgressReporter


class FakeClient:
    def __init__(self, calls):
        self._calls = calls

    def progress(self, job_id, current_step, **fields):
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
