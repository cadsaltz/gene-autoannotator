from unittest.mock import patch

from worker.router.ollama_ps import (
    clear_ps_cache,
    dashboard_ollama_ps_enabled,
    parse_ps_payload,
    residency_snapshot_from_ps,
)


def test_parse_ps_payload_models_object():
    rows = parse_ps_payload(
        {
            "models": [
                {"model": "gemma3:27b", "size": 17_000_000_000, "size_vram": 8_000_000_000},
                {"name": "qwen3:8b", "size": 5_000_000_000},
            ]
        }
    )
    assert rows == [
        {
            "model": "gemma3:27b",
            "size_bytes": 17_000_000_000,
            "size_vram_bytes": 8_000_000_000,
        },
        {
            "model": "qwen3:8b",
            "size_bytes": 5_000_000_000,
            "size_vram_bytes": 0,
        },
    ]


def test_parse_ps_payload_list_form():
    rows = parse_ps_payload([{"model": "mistral-nemo:12b", "size_vram": 7_100_000_000}])
    assert rows[0]["model"] == "mistral-nemo:12b"
    assert rows[0]["size_bytes"] == 7_100_000_000


def test_dashboard_ps_kill_switch(monkeypatch):
    monkeypatch.setenv("WORKER_DASHBOARD_OLLAMA_PS", "0")
    clear_ps_cache()
    assert dashboard_ollama_ps_enabled() is False
    snap = residency_snapshot_from_ps(
        "http://127.0.0.1:11434",
        budget_bytes=100,
        in_flight={"qwen3:14b": 1},
    )
    assert snap is not None
    assert snap["ps_disabled"] is True
    assert snap["models"] == [{"model": "qwen3:14b", "size_bytes": 0, "in_flight": 1}]


def test_dashboard_ps_enabled_by_default(monkeypatch):
    monkeypatch.delenv("WORKER_DASHBOARD_OLLAMA_PS", raising=False)
    assert dashboard_ollama_ps_enabled() is True


def test_ps_results_are_cached_across_calls(monkeypatch):
    monkeypatch.setenv("WORKER_DASHBOARD_OLLAMA_PS", "1")
    monkeypatch.setenv("WORKER_DASHBOARD_OLLAMA_PS_INTERVAL_SEC", "30")
    clear_ps_cache()
    calls = {"n": 0}

    def fake_list(host, *, timeout_sec=0.5):
        calls["n"] += 1
        return [{"model": "qwen3:14b", "size_bytes": 14_000_000_000, "size_vram_bytes": 0}]

    with patch("worker.router.ollama_ps.list_resident_models", side_effect=fake_list):
        snap1 = residency_snapshot_from_ps(
            "http://127.0.0.1:11434",
            budget_bytes=24_000_000_000,
            in_flight={"qwen3:14b": 1},
        )
        snap2 = residency_snapshot_from_ps(
            "http://127.0.0.1:11434",
            budget_bytes=24_000_000_000,
            in_flight={"qwen3:14b": 2},
        )
    assert calls["n"] == 1
    assert snap1["models"][0]["in_flight"] == 1
    assert snap2["models"][0]["in_flight"] == 2
    assert snap2["models"][0]["size_bytes"] == 14_000_000_000
