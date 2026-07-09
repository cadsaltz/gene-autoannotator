import os

from worker.config import WorkerConfig
from worker.fleet.config import FleetConfig
from worker.probe import SystemSpec
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

    def fake_run_annotation_job(request, *, job_id=None):
        captured["profile"] = request.profile
        captured["locus"] = request.locus
        captured["job_id"] = job_id
        return {"ok": True}

    monkeypatch.setattr(serve.executor, "run_annotation_job", fake_run_annotation_job)
    result = serve._execute_job({"profile": "mtb-h37rv", "locus": "Rv0001"}, job_id="j-1")
    assert result == {"ok": True}
    assert captured == {"profile": "mtb-h37rv", "locus": "Rv0001", "job_id": "j-1"}
