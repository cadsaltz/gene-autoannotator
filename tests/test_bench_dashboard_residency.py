from worker.bench_dashboard import render_dashboard


def test_render_dashboard_shows_models_in_mem():
    text = render_dashboard(
        snapshot={"jobs_completed": 0, "jobs_total": 1, "jobs_failed": 0, "active": []},
        hw={"gpus": None, "gpu_error": "no gpu", "cpu_percent": 1.0, "ram": "1/16 GB"},
        meta={
            "slots": 2,
            "models_in_mem": {
                "used_bytes": 17 * 1024**3,
                "budget_bytes": 24 * 1024**3,
                "ps_disabled": False,
                "models": [
                    {"model": "gemma3:27b", "size_bytes": 17 * 1024**3, "in_flight": 1},
                ],
            },
        },
    )
    assert "IN MEM" in text
    assert "gemma3:27b" in text
    assert "17.0/24.0 GiB" in text


def test_render_dashboard_shows_ps_disabled():
    text = render_dashboard(
        snapshot={"jobs_completed": 0, "jobs_total": 1, "jobs_failed": 0, "active": []},
        hw={"gpus": None, "gpu_error": "no gpu", "cpu_percent": 1.0, "ram": "1/16 GB"},
        meta={
            "slots": 2,
            "models_in_mem": {
                "used_bytes": 0,
                "budget_bytes": 24 * 1024**3,
                "models": [{"model": "qwen3:14b", "size_bytes": 0, "in_flight": 1}],
                "ps_disabled": True,
            },
        },
    )
    assert "ollama ps disabled" in text
    assert "qwen3:14b" in text
    assert "●○" in text or "●" in text
