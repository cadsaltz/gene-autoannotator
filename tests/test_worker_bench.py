import json
import logging
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from worker.fleet.config import FleetConfig
from worker.probe import SystemSpec
from worker.router.metrics import MetricsCollector
from worker.sources.batch import BatchJobSource
from worker import bench


class _FakeRouterServer:
    def shutdown(self):
        return None

    def server_close(self):
        return None


class _FakeSupervisor:
    def shutdown(self) -> None:
        return None


class _FakeRouterThread:
    def __init__(self):
        self._port = 12345
        self._server = _FakeRouterServer()
        self._metrics = MetricsCollector()
        self._metrics.begin_batch()

    def join(self, timeout=None):
        return None


def _spec():
    return SystemSpec(
        gpu_count=1,
        vram_bytes=(8 * 1024**3,),
        system_ram_bytes=64 * 1024**3,
        cpu_physical=8,
        cpu_logical=16,
    )


def test_configure_bench_logging_to_file(tmp_path):
    log_path = tmp_path / "worker.log"
    bench.configure_bench_logging(log_file=log_path, dashboard=True)
    try:
        logging.getLogger("autoannotation").info("hello-file")
    finally:
        logging.getLogger().handlers.clear()
    assert "hello-file" in log_path.read_text()


def test_configure_bench_logging_without_dashboard_streams_to_stdout(tmp_path, capsys):
    bench.configure_bench_logging(log_file=None, dashboard=False)
    try:
        logging.getLogger("autoannotation").info("hello-stdout")
    finally:
        logging.getLogger().handlers.clear()
    assert "hello-stdout" in capsys.readouterr().out


def test_batch_job_source_assigns_ids_and_exhaustion(tmp_path):
    jobs_path = tmp_path / "jobs.jsonl"
    jobs_path.write_text(
        '{"profile":"mtb-h37rv","locus":"Rv0001","allow_online_name_lookup":false}\n'
        '{"profile":"mtb-h37rv","locus":"Rv0002","allow_online_name_lookup":false}\n',
        encoding="utf-8",
    )
    source = BatchJobSource(jobs_path)
    assert source.jobs_submitted == 2

    first = source.claim_one()
    second = source.claim_one()
    assert first is not None
    assert second is not None
    assert first.job_id == "bench-001"
    assert second.job_id == "bench-002"
    assert source.claim_one() is None
    assert source.is_exhausted() is False

    source.on_complete(first.job_id, {"ok": True})
    source.on_fail(second.job_id, "boom", retryable=False)
    assert source.is_exhausted() is True


def test_bench_completes_and_writes_report(tmp_path, monkeypatch):
    report_path = tmp_path / "report.json"
    calls = {"start_fleet": []}

    monkeypatch.setattr(bench, "ensure_worker_env", lambda **_kw: None)
    monkeypatch.setattr(bench, "ensure_fleet_config", lambda **_kw: FleetConfig(1, 1, 2))
    monkeypatch.setattr(bench, "probe_system", _spec)
    monkeypatch.setattr(
        bench,
        "reset_ollama_fleet",
        lambda cfg, spec: calls["start_fleet"].append((cfg, spec)) or _FakeSupervisor(),
    )
    monkeypatch.setattr(bench, "models_loaded", lambda **kw: [])
    monkeypatch.setattr(bench, "ensure_models", lambda client=None: None)
    monkeypatch.setattr(bench, "warm_all_models", lambda **kw: [])
    monkeypatch.setattr(bench, "refresh_fleet_footprints", lambda fleet, spec, **kw: fleet)
    monkeypatch.setattr(bench, "required_model_names", lambda: ["gemma3:1b"])
    monkeypatch.setattr(bench.ollama, "Client", lambda host: {"host": host})
    monkeypatch.setattr(bench, "start_router_server", lambda *a, **k: _FakeRouterThread())
    monkeypatch.setattr(bench, "load_config", lambda: SimpleNamespace(max_slots=2, heartbeat_seconds=1))
    monkeypatch.setattr(
        bench.executor,
        "run_annotation_job",
        lambda request, *, job_id=None, on_progress=None: {"job_id": job_id, "locus": request.locus},
    )

    jobs = Path("tests/fixtures/bench_jobs_2.jsonl")
    rc = bench.main(
        [
            "--jobs",
            str(jobs),
            "--slots",
            "2",
            "--cache",
            "cold",
            "--report",
            str(report_path),
        ]
    )

    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert rc == 0
    assert calls["start_fleet"]
    assert payload["batch"]["jobs_submitted"] == 2
    assert payload["batch"]["jobs_completed"] == 2
    assert "jobs_per_hour" in payload["batch"]


class _StopBench(Exception):
    pass


def test_bench_configure_fleet_prompts_interactively(monkeypatch):
    captured: dict[str, dict] = {}

    def fake_ensure_worker_env(**kwargs):
        captured["ensure_worker_env"] = kwargs

    def fake_ensure_fleet_config(**kwargs):
        captured["ensure_fleet_config"] = kwargs
        return FleetConfig(2, 2, 4)

    monkeypatch.setattr(bench, "ensure_worker_env", fake_ensure_worker_env)
    monkeypatch.setattr(bench, "ensure_fleet_config", fake_ensure_fleet_config)
    monkeypatch.setattr(bench.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(bench, "probe_system", lambda: (_ for _ in ()).throw(_StopBench()))

    with pytest.raises(_StopBench):
        bench.main(["--jobs", "tests/fixtures/bench_jobs_2.jsonl", "--configure-fleet"])

    assert captured["ensure_worker_env"] == {
        "interactive": False,
        "skip_fleet_config": True,
        "require_coordinator": False,
    }
    assert captured["ensure_fleet_config"] == {"interactive": True}


def test_bench_configure_fleet_requires_tty(monkeypatch):
    monkeypatch.setattr(bench.sys.stdin, "isatty", lambda: False)
    rc = bench.main(["--jobs", "tests/fixtures/bench_jobs_2.jsonl", "--configure-fleet"])
    assert rc == 2


def test_bench_output_dir_sets_worker_output_dir(tmp_path, monkeypatch):
    report_path = tmp_path / "report.json"
    output_dir = tmp_path / "annotations"

    monkeypatch.setattr(bench, "ensure_worker_env", lambda **_kw: None)
    monkeypatch.setattr(bench, "ensure_fleet_config", lambda **_kw: FleetConfig(1, 1, 2))
    monkeypatch.setattr(bench, "probe_system", _spec)
    monkeypatch.setattr(bench, "reset_ollama_fleet", lambda cfg, spec: _FakeSupervisor())
    monkeypatch.setattr(bench, "models_loaded", lambda **kw: [])
    monkeypatch.setattr(bench, "ensure_models", lambda client=None: None)
    monkeypatch.setattr(bench, "warm_all_models", lambda **kw: [])
    monkeypatch.setattr(bench, "refresh_fleet_footprints", lambda fleet, spec, **kw: fleet)
    monkeypatch.setattr(bench, "required_model_names", lambda: ["gemma3:1b"])
    monkeypatch.setattr(bench.ollama, "Client", lambda host: {"host": host})
    monkeypatch.setattr(bench, "start_router_server", lambda *a, **k: _FakeRouterThread())
    monkeypatch.setattr(bench, "load_config", lambda: SimpleNamespace(max_slots=2, heartbeat_seconds=1))
    captured = {}

    def fake_run(request, *, job_id=None, on_progress=None):
        captured["output_dir"] = os.environ.get("WORKER_OUTPUT_DIR")
        return {"job_id": job_id}

    monkeypatch.setattr(bench.executor, "run_annotation_job", fake_run)

    jobs = Path("tests/fixtures/bench_jobs_2.jsonl")
    bench.main(
        [
            "--jobs",
            str(jobs),
            "--slots",
            "2",
            "--cache",
            "cold",
            "--report",
            str(report_path),
            "--output-dir",
            str(output_dir),
        ]
    )
    assert captured["output_dir"] == str(output_dir.resolve())
    assert output_dir.is_dir()
