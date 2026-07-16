import threading
from unittest.mock import MagicMock

from worker import hw_probe
from worker.bench_dashboard import BenchDashboard, render_dashboard


def test_render_dashboard_includes_batch_and_gpu_unavailable():
    text = render_dashboard(
        snapshot={
            "jobs_done": 5,
            "jobs_total": 100,
            "jobs_failed": 1,
            "active": [
                {
                    "job_id": "bench-001",
                    "locus": "TcCLB.1",
                    "elapsed_s": 12.0,
                    "progress": {
                        "phase": "extracting",
                        "sections_done": 2,
                        "sections_total": 9,
                        "pass_name": "target",
                    },
                }
            ],
        },
        hw={"gpus": None, "gpu_error": "nvidia-smi not found", "cpu_percent": 10.0, "ram": "1/16 GB"},
        meta={"fleet": "2x2", "elapsed_s": 60.0},
        spinner_frame="⠋",
    )
    assert "5/100" in text
    assert "1 failed" in text or "failed" in text.lower()
    assert "bench-001" in text
    assert "2/9" in text
    assert "nvidia-smi not found" in text


def test_render_dashboard_accepts_jobs_completed_alias():
    text = render_dashboard(
        snapshot={"jobs_completed": 3, "jobs_total": 10, "jobs_failed": 0, "active": []},
        hw={"gpus": None, "gpu_error": "no gpu", "cpu_percent": None, "ram": "?/? GB"},
    )
    assert "3/10" in text


def test_render_dashboard_shows_gpu_stats():
    gpu = hw_probe.GpuStat(
        index=0,
        name="NVIDIA A100",
        util_percent=72.0,
        mem_used_mb=61234,
        mem_total_mb=81920,
        temp_c=64.0,
    )
    text = render_dashboard(
        snapshot={"jobs_completed": 0, "jobs_total": 1, "jobs_failed": 0, "active": []},
        hw={"gpus": [gpu], "gpu_error": None, "cpu_percent": 50.0, "ram": "8/80 GB"},
    )
    assert "NVIDIA A100" in text
    assert "72" in text


def test_run_live_does_not_raise_when_probes_fail(monkeypatch):
    monkeypatch.setattr(hw_probe, "probe_gpus", lambda: (_ for _ in ()).throw(OSError("boom")))
    monkeypatch.setattr(hw_probe, "probe_cpu_ram", lambda **kwargs: (_ for _ in ()).throw(OSError("boom")))
    monkeypatch.setattr(hw_probe, "read_proc_stat_sample", lambda: (_ for _ in ()).throw(OSError("boom")))
    monkeypatch.setattr(hw_probe, "probe_ollama_cpu_percent", lambda: (_ for _ in ()).throw(OSError("boom")))

    runtime = MagicMock()
    runtime.snapshot.return_value = {
        "jobs_completed": 0,
        "jobs_total": 1,
        "jobs_failed": 0,
        "active": [],
    }
    stop = threading.Event()
    stop.set()

    dashboard = BenchDashboard()
    dashboard.run_live(runtime, stop, refresh_sec=0.01)
