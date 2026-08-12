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


def test_render_dashboard_shows_waiting_on_ollama_load():
    text = render_dashboard(
        snapshot={"jobs_completed": 0, "jobs_total": 2, "jobs_failed": 0, "active": []},
        hw={"gpus": None, "gpu_error": "no gpu", "cpu_percent": 1.0, "ram": "3/31 GB"},
        meta={
            "slots": 2,
            "models_in_mem": {
                "used_bytes": 0,
                "budget_bytes": 24 * 1024**3,
                "ps_disabled": False,
                "models": [
                    {"model": "qwen3:14b", "size_bytes": 0, "in_flight": 2},
                ],
            },
            "ollama_servers": [
                {
                    "host": "http://127.0.0.1:11434",
                    "pid": 219,
                    "status": "running",
                    "log_path": "/out/annotations/ollama-server-11434.log",
                    "summary": {"phase": "unknown", "alerts": []},
                }
            ],
        },
    )
    assert "waiting on Ollama load" in text
    assert "cold-start" in text
    assert "phase: waiting on load" in text
    assert "qwen3:14b" in text
    assert "◐◐" in text


def test_render_dashboard_shows_loading_into_memory_note():
    text = render_dashboard(
        snapshot={"jobs_completed": 0, "jobs_total": 1, "jobs_failed": 0, "active": []},
        hw={"gpus": None, "gpu_error": "no gpu", "cpu_percent": 1.0, "ram": "10/31 GB"},
        meta={
            "slots": 2,
            "models_in_mem": {
                "used_bytes": 14 * 1024**3,
                "budget_bytes": 24 * 1024**3,
                "ps_disabled": False,
                "models": [
                    {"model": "qwen3:14b", "size_bytes": 14 * 1024**3, "in_flight": 2},
                ],
            },
            "ollama_servers": [
                {
                    "host": "http://127.0.0.1:11434",
                    "status": "running",
                    "summary": {
                        "phase": "loading",
                        "layers_on_gpu": 21,
                        "layers_total": 41,
                        "alerts": [],
                    },
                }
            ],
        },
    )
    assert "loading into memory" in text
    assert "◐◐" in text


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
    assert "waiting on Ollama load" in text
    assert "◐○" in text
