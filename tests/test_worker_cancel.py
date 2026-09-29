import threading
import time
from types import SimpleNamespace

import httpx
import pytest

from shared.job_progress import JobProgressEvent
from worker import executor
from worker.client import BackendClient, JobCancelled
from worker.progress_reporter import ProgressReporter
from worker.runtime import JobSpec, WorkerRuntime


class _Config:
    backend_url = "http://backend.test"
    worker_api_token = "tok"
    worker_name = "w"
    hostname = "h"
    agent_version = "test"
    total_memory_bytes = 1
    dedicated_memory_bytes = 1
    max_slots = 1


class _Http:
    def __init__(self, response):
        self.response = response
        self.calls = 0

    def patch(self, path, headers=None, json=None):
        del path, headers, json
        self.calls += 1
        return self.response


def _response(method, path, status, **kwargs):
    return httpx.Response(
        status, request=httpx.Request(method, f"http://backend.test{path}"), **kwargs
    )


def test_progress_raises_job_cancelled_on_409_with_cancelled_flag():
    resp = _response(
        "PATCH", "/jobs/j1/progress", 409, json={"detail": "Job cancelled", "cancelled": True}
    )
    client = BackendClient(_Config(), http_client=_Http(resp))

    with pytest.raises(JobCancelled) as exc_info:
        client.progress("j1", "step")

    assert exc_info.value.job_id == "j1"


def test_progress_plain_409_keeps_raising_http_status_error():
    resp = _response("PATCH", "/jobs/j1/progress", 409, json={"detail": "Job is not running"})
    client = BackendClient(_Config(), http_client=_Http(resp))

    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        client.progress("j1", "step")

    assert not isinstance(exc_info.value, JobCancelled)


def test_progress_409_with_non_json_body_keeps_raising_http_status_error():
    resp = _response("PATCH", "/jobs/j1/progress", 409, text="conflict")
    client = BackendClient(_Config(), http_client=_Http(resp))

    with pytest.raises(httpx.HTTPStatusError):
        client.progress("j1", "step")


class _FakeClock:
    def __init__(self):
        self.now = 1000.0
        self.sleeps = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


class _ScriptedPost:
    def __init__(self, items):
        self._items = list(items)
        self.calls = 0

    def post(self, path, headers=None, json=None):
        del path, headers, json
        self.calls += 1
        item = self._items.pop(0) if len(self._items) > 1 else self._items[0]
        if isinstance(item, BaseException):
            raise item
        return item


def test_complete_retries_for_configured_window(monkeypatch):
    monkeypatch.setenv("WORKER_COMPLETE_RETRY_SECONDS", "10")
    sleeps = []
    monkeypatch.setattr(time, "sleep", lambda s: sleeps.append(s))
    ok = _response("POST", "/jobs/j1/complete", 204)
    http = _ScriptedPost([httpx.ConnectError("down")] * 5 + [ok])

    BackendClient(_Config(), http_client=http).complete("j1", {})

    assert http.calls == 6
    assert len(sleeps) == 5


def test_complete_backoff_grows_and_caps_at_thirty_seconds(monkeypatch):
    clock = _FakeClock()
    monkeypatch.setattr(time, "monotonic", clock.monotonic)
    monkeypatch.setattr(time, "sleep", clock.sleep)
    monkeypatch.delenv("WORKER_COMPLETE_RETRY_SECONDS", raising=False)
    ok = _response("POST", "/jobs/j1/complete", 204)
    http = _ScriptedPost([httpx.ConnectError("down")] * 9 + [ok])

    BackendClient(_Config(), http_client=http).complete("j1", {})

    assert clock.sleeps == [0.5, 1.0, 2.0, 4.0, 8.0, 16.0, 30.0, 30.0, 30.0]


def test_complete_gives_up_after_window_and_raises_last_transport_error(monkeypatch):
    clock = _FakeClock()
    monkeypatch.setattr(time, "monotonic", clock.monotonic)
    monkeypatch.setattr(time, "sleep", clock.sleep)
    monkeypatch.setenv("WORKER_COMPLETE_RETRY_SECONDS", "10")
    http = _ScriptedPost([httpx.ConnectError("down")])

    with pytest.raises(httpx.ConnectError):
        BackendClient(_Config(), http_client=http).complete("j1", {})

    assert sum(clock.sleeps) == pytest.approx(10.0)
    assert http.calls == len(clock.sleeps) + 1


def test_complete_retries_gateway_errors_during_backend_swap(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda _s: None)
    http = _ScriptedPost(
        [
            _response("POST", "/jobs/j1/complete", 502),
            _response("POST", "/jobs/j1/complete", 503),
            _response("POST", "/jobs/j1/complete", 504),
            _response("POST", "/jobs/j1/complete", 204),
        ]
    )

    BackendClient(_Config(), http_client=http).complete("j1", {})

    assert http.calls == 4


def test_complete_does_not_retry_500(monkeypatch):
    sleeps = []
    monkeypatch.setattr(time, "sleep", lambda s: sleeps.append(s))
    http = _ScriptedPost([_response("POST", "/jobs/j1/complete", 500)])

    with pytest.raises(httpx.HTTPStatusError):
        BackendClient(_Config(), http_client=http).complete("j1", {})

    assert http.calls == 1
    assert sleeps == []


class _RecordingPost:
    def __init__(self):
        self.bodies = []

    def post(self, path, headers=None, json=None):
        del headers
        self.bodies.append(json)
        return _response("POST", path, 204)


def test_complete_and_fail_identify_the_registered_worker():
    http = _RecordingPost()
    client = BackendClient(_Config(), http_client=http)
    client.worker_id = "worker-a"

    client.complete("j1", {"ok": True})
    client.fail("j2", "boom", True)

    assert http.bodies == [
        {"result": {"ok": True}, "worker_id": "worker-a"},
        {"error": "boom", "retryable": True, "worker_id": "worker-a"},
    ]


def test_complete_and_fail_omit_worker_id_when_unregistered():
    http = _RecordingPost()
    client = BackendClient(_Config(), http_client=http)

    client.complete("j1", {"ok": True})
    client.fail("j2", "boom", False)

    assert http.bodies == [
        {"result": {"ok": True}},
        {"error": "boom", "retryable": False},
    ]


def test_fail_retries_across_backend_restart(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda _s: None)
    http = _ScriptedPost(
        [
            httpx.ConnectError("down"),
            _response("POST", "/jobs/j1/fail", 503),
            httpx.ReadTimeout("slow"),
            _response("POST", "/jobs/j1/fail", 204),
        ]
    )

    BackendClient(_Config(), http_client=http).fail("j1", "boom", True)

    assert http.calls == 4


def test_complete_gives_up_on_persistent_5xx_with_http_status_error(monkeypatch):
    clock = _FakeClock()
    monkeypatch.setattr(time, "monotonic", clock.monotonic)
    monkeypatch.setattr(time, "sleep", clock.sleep)
    monkeypatch.setenv("WORKER_COMPLETE_RETRY_SECONDS", "5")
    http = _ScriptedPost([_response("POST", "/jobs/j1/complete", 503)])

    with pytest.raises(httpx.HTTPStatusError):
        BackendClient(_Config(), http_client=http).complete("j1", {})

    assert sum(clock.sleeps) == pytest.approx(5.0)


@pytest.mark.parametrize("status", [400, 401, 404, 409, 422])
def test_complete_does_not_retry_4xx(monkeypatch, status):
    sleeps = []
    monkeypatch.setattr(time, "sleep", lambda s: sleeps.append(s))
    http = _ScriptedPost([_response("POST", "/jobs/j1/complete", status)])

    with pytest.raises(httpx.HTTPStatusError):
        BackendClient(_Config(), http_client=http).complete("j1", {})

    assert http.calls == 1
    assert sleeps == []


def test_claim_keeps_short_retry_and_does_not_retry_5xx(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda _s: None)
    http = _ScriptedPost([_response("POST", "/workers/w1/claim", 503)])
    client = BackendClient(_Config(), http_client=http)
    client.worker_id = "w1"

    with pytest.raises(httpx.HTTPStatusError):
        client.claim(free_slots=1)

    assert http.calls == 1


class _CancellingClient:
    def __init__(self):
        self.calls = []

    def progress(self, job_id, current_step, **fields):
        self.calls.append(job_id)
        raise JobCancelled(job_id)


def _event(phase="fetching", done=1):
    return JobProgressEvent(phase=phase, sections_done=done, sections_total=10)


def test_reporter_invokes_on_cancelled_once_and_stops_sending():
    client = _CancellingClient()
    cancelled = []
    reporter = ProgressReporter(client, debounce_sec=0.0, on_cancelled=cancelled.append)

    reporter.report("j1", _event(done=1))
    reporter.report("j1", _event(phase="extracting", done=2))
    reporter.flush("j1")
    reporter.close()

    assert cancelled == ["j1"]
    assert client.calls == ["j1"]


def test_reporter_on_cancelled_can_be_wired_after_construction():
    reporter = ProgressReporter(_CancellingClient(), debounce_sec=0.0)
    cancelled = []
    reporter.on_cancelled = cancelled.append

    reporter.report("j1", _event())

    assert cancelled == ["j1"]


def test_reporter_swallows_on_cancelled_callback_errors():
    invoked = []

    def boom(job_id):
        invoked.append(job_id)
        raise RuntimeError("callback broke")

    client = _CancellingClient()
    reporter = ProgressReporter(client, debounce_sec=0.0, on_cancelled=boom)

    reporter.report("j1", _event(done=1))
    reporter.report("j1", _event(phase="extracting", done=2))

    assert invoked == ["j1"]
    assert client.calls == ["j1"]


class _RecordingSource:
    def __init__(self, jobs):
        self._jobs = list(jobs)
        self.completed = []
        self.failed = []
        self.cancelled = []

    def claim_one(self):
        return self._jobs.pop(0) if self._jobs else None

    def on_complete(self, job_id, result):
        self.completed.append((job_id, result))

    def on_fail(self, job_id, error, retryable):
        self.failed.append((job_id, error, retryable))

    def on_cancelled(self, job_id):
        self.cancelled.append(job_id)

    def is_exhausted(self):
        return not self._jobs

    def wait_or_sleep(self, timeout):
        time.sleep(min(timeout, 0.01))


def _runtime(source, execute_fn, *, max_slots=1):
    return WorkerRuntime(
        config=SimpleNamespace(max_slots=max_slots, heartbeat_seconds=15),
        fleet_config=SimpleNamespace(max_slots=max_slots),
        job_source=source,
        execute_fn=execute_fn,
    )


def _wait_for(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def test_cancel_job_terminates_process_frees_slot_and_reports_nothing(monkeypatch):
    started = threading.Event()
    terminated = threading.Event()
    terminate_calls = []

    def fake_terminate_job(job_id):
        terminate_calls.append(job_id)
        terminated.set()
        return True

    monkeypatch.setattr(executor, "terminate_job", fake_terminate_job)

    def execute(request, *, job_id=None):
        started.set()
        assert terminated.wait(5)
        raise RuntimeError("annotation subprocess failed with exit code -15")

    source = _RecordingSource([JobSpec(job_id="j1", request={"locus": "Rv0001"})])
    runtime = _runtime(source, execute)

    runtime._claim_to_capacity()
    assert started.wait(5)
    assert runtime.free_slots() == 0

    runtime.cancel_job("j1")

    assert terminate_calls == ["j1"]
    future = runtime.active_jobs["j1"].future
    assert _wait_for(future.done)
    runtime._reap_finished()

    assert runtime.free_slots() == 1
    assert source.completed == []
    assert source.failed == []
    assert source.cancelled == ["j1"]
    assert runtime.snapshot()["jobs_failed"] == 0
    assert runtime.snapshot()["jobs_completed"] == 0


def test_cancelled_job_that_still_returns_a_result_is_not_completed(monkeypatch):
    monkeypatch.setattr(executor, "terminate_job", lambda _job_id: True)
    release = threading.Event()

    def execute(request, *, job_id=None):
        assert release.wait(5)
        return {"locus": request["locus"]}

    source = _RecordingSource([JobSpec(job_id="j1", request={"locus": "Rv0001"})])
    runtime = _runtime(source, execute)

    runtime._claim_to_capacity()
    runtime.cancel_job("j1")
    release.set()
    assert _wait_for(runtime.active_jobs["j1"].future.done)
    runtime._reap_finished()

    assert source.completed == []
    assert source.failed == []
    assert runtime.free_slots() == 1


def test_cancel_warns_when_no_subprocess_can_be_stopped(monkeypatch, caplog):
    import logging

    monkeypatch.setattr(executor, "terminate_job", lambda _job_id: False)
    release = threading.Event()

    def execute(request, *, job_id=None):
        assert release.wait(5)
        return {}

    runtime = _runtime(_RecordingSource([JobSpec(job_id="j1", request={})]), execute)
    runtime._claim_to_capacity()
    caplog.set_level(logging.WARNING, logger="worker.runtime")

    runtime.cancel_job("j1")
    release.set()

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any("j1" in r.getMessage() for r in warnings)


def test_cancel_unknown_job_is_a_noop(monkeypatch):
    calls = []
    monkeypatch.setattr(executor, "terminate_job", lambda job_id: calls.append(job_id))
    runtime = _runtime(_RecordingSource([]), lambda request: {})

    runtime.cancel_job("nope")

    assert calls == []


def test_run_loop_exits_after_cancelled_one_shot_job(monkeypatch):
    terminated = threading.Event()
    monkeypatch.setattr(executor, "terminate_job", lambda _job_id: terminated.set() or True)
    started = threading.Event()

    def execute(request, *, job_id=None):
        started.set()
        assert terminated.wait(5)
        raise RuntimeError("annotation subprocess failed with exit code -15")

    source = _RecordingSource([JobSpec(job_id="j1", request={"locus": "Rv0001"})])
    runtime = _runtime(source, execute)
    thread = threading.Thread(target=runtime.run, daemon=True)
    thread.start()
    assert started.wait(5)

    runtime.cancel_job("j1")
    thread.join(timeout=5)

    assert not thread.is_alive()
    assert source.completed == []
    assert source.failed == []
    assert source.cancelled == ["j1"]


def test_progress_409_through_reporter_stops_the_running_job(monkeypatch):
    terminated = threading.Event()
    monkeypatch.setattr(executor, "terminate_job", lambda _job_id: terminated.set() or True)
    reporter = ProgressReporter(_CancellingClient(), debounce_sec=0.0)

    def execute(request, *, job_id=None, on_progress=None):
        reporter.report(job_id, _event())
        assert terminated.wait(5)
        raise RuntimeError("annotation subprocess failed with exit code -15")

    source = _RecordingSource([JobSpec(job_id="j1", request={"locus": "Rv0001"})])
    runtime = _runtime(source, execute)
    reporter.on_cancelled = runtime.cancel_job
    thread = threading.Thread(target=runtime.run, daemon=True)
    thread.start()
    thread.join(timeout=5)

    assert not thread.is_alive()
    assert source.completed == []
    assert source.failed == []
    assert source.cancelled == ["j1"]


def test_one_shot_source_is_exhausted_after_its_job_is_cancelled():
    from worker import run

    job = JobSpec(job_id="j1", request={"locus": "Rv0001"})
    source = run._OneShotJobSource(object(), job, ProgressReporter(object()))
    assert source.claim_one() == job
    assert source.is_exhausted() is False

    source.on_cancelled("j1")

    assert source.is_exhausted() is True
    assert source.failed is False


def test_executor_terminate_job_signals_only_that_job(monkeypatch):
    class FakeProc:
        def __init__(self):
            self.terminated = False
            self.killed = False

        def terminate(self):
            self.terminated = True

        def kill(self):
            self.killed = True

        def wait(self, timeout=None):
            return 0

    target, other = FakeProc(), FakeProc()
    monkeypatch.setattr(executor, "_active_processes", {"j1": target, "j2": other})

    assert executor.terminate_job("j1") is True
    assert executor.terminate_job("missing") is False

    assert target.terminated is True
    assert other.terminated is False


def test_executor_terminate_job_kills_real_subprocess():
    import subprocess
    import sys

    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    executor._register_job_process("real-job", proc)
    try:
        assert executor.terminate_job("real-job") is True
        assert proc.wait(timeout=10) != 0
    finally:
        executor._unregister_job_process("real-job", proc)
        if proc.poll() is None:
            proc.kill()
