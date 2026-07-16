import argparse
import os
import threading

from shared.job_progress import JobProgressEvent
from worker.config import WorkerConfig
from worker.fleet.config import FleetConfig
from worker.probe import SystemSpec
from worker.progress_reporter import ProgressReporter
from worker import serve


def _config():
    return WorkerConfig(
        coordinator_url="http://localhost:8000",
        worker_api_token="t",
        worker_name="w1",
        hostname="w1",
        dedicated_memory_bytes=42_000_000_000,
        total_memory_bytes=64_000_000_000,
        max_slots=3,
        agent_version="0.1.0",
    )


def _spec():
    return SystemSpec(
        gpu_count=1,
        vram_bytes=(8 * 1024**3,),
        system_ram_bytes=64 * 1024**3,
        cpu_physical=8,
        cpu_logical=16,
    )


def test_main_wires_runtime_router_and_heartbeat(monkeypatch):
    monkeypatch.delenv("OLLAMA_ROUTER_URL", raising=False)
    calls = {"ensure_models": [], "start_fleet": [], "heartbeats": []}
    captured = {}

    class FakeClient:
        def __init__(self, _cfg):
            self.worker_id = "w1"

        def register(self):
            return "w1"

        def heartbeat(self, **kw):
            calls["heartbeats"].append(kw)
            if kw["state"] == "ready":
                return {"required_version": "2.0.0", "drain": True}
            return {"required_version": None, "drain": False}

    class FakeRuntime:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def run(self):
            captured["heartbeat_fn"](active_jobs=0, free_slots=3)
            captured["heartbeat_fn"](active_jobs=0, free_slots=3)
            return None

    class FakeRouterThread:
        _port = 11999

    monkeypatch.setattr(serve, "ensure_worker_env", lambda **_kw: None)
    monkeypatch.setattr(serve, "ensure_fleet_config", lambda **_kw: FleetConfig(2, 2, 3))
    monkeypatch.setattr(serve, "probe_system", _spec)
    monkeypatch.setattr(
        serve,
        "reset_ollama_fleet",
        lambda cfg, spec: calls["start_fleet"].append((cfg, spec)) or [],
    )
    monkeypatch.setattr(serve.ollama, "Client", lambda host: {"host": host})
    monkeypatch.setattr(
        serve, "ensure_models", lambda client=None: calls["ensure_models"].append(client)
    )
    monkeypatch.setattr(serve, "required_model_names", lambda: ["m1", "m2"])
    monkeypatch.setattr(serve, "start_router_server", lambda *a, **k: FakeRouterThread())
    monkeypatch.setattr(serve, "load_config", _config)
    monkeypatch.setattr(serve, "CoordinatorClient", FakeClient)
    monkeypatch.setattr(serve, "WorkerRuntime", FakeRuntime)
    monkeypatch.setattr(serve.capacity, "can_admit", lambda *_a, **_k: True)
    monkeypatch.setattr(serve, "_memory_available_bytes", lambda: 1 << 62)
    monkeypatch.setattr(serve, "_cpu_percent", lambda: 0.0)

    serve.main()

    assert calls["start_fleet"]
    assert calls["ensure_models"] == [{"host": "http://127.0.0.1:11434"}]
    assert os.environ["OLLAMA_ROUTER_URL"] == "http://127.0.0.1:11999"
    assert calls["heartbeats"][0]["state"] == "ready"
    assert calls["heartbeats"][-1]["state"] == "draining"
    assert captured["job_source"].is_exhausted() is True


def test_execute_fn_passes_job_id(monkeypatch):
    captured = {}

    def fake_run_annotation_job(request, *, job_id=None, on_progress=None):
        captured["profile"] = request.profile
        captured["locus"] = request.locus
        captured["job_id"] = job_id
        captured["on_progress"] = on_progress
        return {"ok": True}

    monkeypatch.setattr(serve.executor, "run_annotation_job", fake_run_annotation_job)
    result = serve._execute_job({"profile": "mtb-h37rv", "locus": "Rv0001"}, job_id="j-1")
    assert result == {"ok": True}
    assert captured["profile"] == "mtb-h37rv"
    assert captured["locus"] == "Rv0001"
    assert captured["job_id"] == "j-1"
    assert captured["on_progress"] is None


def test_execute_fn_forwards_on_progress(monkeypatch):
    captured = {}

    def fake_run_annotation_job(request, *, job_id=None, on_progress=None):
        captured["on_progress"] = on_progress
        return {"ok": True}

    monkeypatch.setattr(serve.executor, "run_annotation_job", fake_run_annotation_job)
    sentinel = object()
    serve._execute_job({"profile": "mtb-h37rv", "locus": "Rv0001"}, job_id="j-1", on_progress=sentinel)
    assert captured["on_progress"] is sentinel


def test_dashboard_enabled_requires_tty_and_respects_flags(monkeypatch):
    monkeypatch.setattr(serve.sys.stdout, "isatty", lambda: True)
    monkeypatch.delenv("WORKER_SERVE_DASHBOARD", raising=False)
    assert serve._dashboard_enabled(argparse.Namespace()) is True
    assert serve._dashboard_enabled(argparse.Namespace(no_dashboard=True)) is False

    monkeypatch.setenv("WORKER_SERVE_DASHBOARD", "0")
    assert serve._dashboard_enabled(argparse.Namespace()) is False

    monkeypatch.setattr(serve.sys.stdout, "isatty", lambda: False)
    monkeypatch.delenv("WORKER_SERVE_DASHBOARD", raising=False)
    assert serve._dashboard_enabled(argparse.Namespace()) is False


def test_resolve_log_file_defaults_to_output_dir_then_cwd(tmp_path, monkeypatch):
    monkeypatch.delenv("WORKER_LOG_FILE", raising=False)
    monkeypatch.delenv("WORKER_OUTPUT_DIR", raising=False)

    assert serve._resolve_log_file(args=argparse.Namespace(), dashboard=False) is None

    monkeypatch.chdir(tmp_path)
    log_file = serve._resolve_log_file(args=argparse.Namespace(), dashboard=True)
    assert log_file == tmp_path / "worker-serve.log"

    output_dir = tmp_path / "out"
    monkeypatch.setenv("WORKER_OUTPUT_DIR", str(output_dir))
    log_file = serve._resolve_log_file(args=argparse.Namespace(), dashboard=True)
    assert log_file == output_dir / "worker-serve.log"


def test_run_with_dashboard_disabled_calls_runtime_run_directly():
    calls = []

    class FakeRuntime:
        def run(self):
            calls.append("run")

    serve._run_with_dashboard(FakeRuntime(), dashboard=False, meta={})
    assert calls == ["run"]


def test_run_with_dashboard_enabled_starts_and_stops_dashboard_thread(monkeypatch):
    started = threading.Event()
    stopped = threading.Event()

    def fake_run_live(self, runtime, stop_event, *, meta=None):
        started.set()
        stop_event.wait(timeout=2)
        stopped.set()

    monkeypatch.setattr(serve.BenchDashboard, "run_live", fake_run_live)

    class FakeRuntime:
        def run(self):
            assert started.wait(timeout=2)

    serve._run_with_dashboard(FakeRuntime(), dashboard=True, meta={"mode": "serve"})
    assert stopped.is_set()


class _FakeCoordinatorClient:
    def __init__(self, *, progress_raises=False):
        self.calls = []
        self.completed = []
        self.failed = []
        self.progress_raises = progress_raises

    def progress(self, job_id, current_step, **fields):
        if self.progress_raises:
            raise RuntimeError("PATCH /jobs/{id}/progress failed")
        self.calls.append({"job_id": job_id, "current_step": current_step, **fields})

    def complete(self, job_id, result):
        self.completed.append((job_id, result))

    def fail(self, job_id, error, retryable):
        self.failed.append((job_id, error, retryable))


def test_make_execute_fn_reports_progress_and_forwards_to_runtime(monkeypatch):
    client = _FakeCoordinatorClient()
    reporter = ProgressReporter(client, debounce_sec=10.0)
    runtime_seen = []

    def fake_run_annotation_job(request, *, job_id=None, on_progress=None):
        on_progress(JobProgressEvent(phase="fetching", sections_done=0, sections_total=3))
        return {"ok": True}

    monkeypatch.setattr(serve.executor, "run_annotation_job", fake_run_annotation_job)
    execute = serve._make_execute_fn(reporter)
    result = execute(
        {"profile": "mtb-h37rv", "locus": "Rv0001"},
        job_id="j-1",
        on_progress=runtime_seen.append,
    )

    assert result == {"ok": True}
    assert len(client.calls) == 1
    assert client.calls[0]["job_id"] == "j-1"
    assert client.calls[0]["phase"] == "fetching"
    assert len(runtime_seen) == 1
    assert runtime_seen[0].phase == "fetching"


def test_drain_aware_source_flushes_reporter_on_complete_and_fail():
    client = _FakeCoordinatorClient()
    reporter = ProgressReporter(client, debounce_sec=10.0)
    source = serve._DrainAwareCoordinatorSource(
        client,
        free_slots_fn=lambda: 1,
        drain_signal=serve._DrainSignal(),
        reporter=reporter,
    )

    reporter.report("j-1", JobProgressEvent(phase="extracting", sections_done=1, sections_total=5))
    reporter.report("j-1", JobProgressEvent(phase="extracting", sections_done=2, sections_total=5))
    assert len(client.calls) == 1

    source.on_complete("j-1", {"ok": True})
    assert len(client.calls) == 2
    assert client.calls[-1]["sections_done"] == 2

    reporter.report("j-2", JobProgressEvent(phase="extracting", sections_done=1, sections_total=5))
    reporter.report("j-2", JobProgressEvent(phase="extracting", sections_done=9, sections_total=5))
    source.on_fail("j-2", "boom", True)
    assert client.calls[-1]["job_id"] == "j-2"
    assert client.calls[-1]["sections_done"] == 9


def test_drain_aware_source_on_complete_and_on_fail_survive_flush_failure():
    """Even if the final progress PATCH would raise, on_complete/on_fail must
    still report completion/failure to the coordinator (Important #1)."""
    client = _FakeCoordinatorClient(progress_raises=True)
    reporter = ProgressReporter(client, debounce_sec=10.0)
    source = serve._DrainAwareCoordinatorSource(
        client,
        free_slots_fn=lambda: 1,
        drain_signal=serve._DrainSignal(),
        reporter=reporter,
    )

    reporter.report("j-1", JobProgressEvent(phase="extracting", sections_done=1, sections_total=5))
    reporter.report("j-1", JobProgressEvent(phase="extracting", sections_done=2, sections_total=5))
    assert client.calls == []  # every send failed

    source.on_complete("j-1", {"ok": True})  # flush's failed PATCH must not raise
    assert client.completed == [("j-1", {"ok": True})]

    reporter.report("j-2", JobProgressEvent(phase="extracting", sections_done=1, sections_total=5))
    source.on_fail("j-2", "boom", True)  # flush's failed PATCH must not raise
    assert client.failed == [("j-2", "boom", True)]
