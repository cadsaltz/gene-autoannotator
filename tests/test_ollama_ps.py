from worker.router.ollama_ps import (
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
    assert dashboard_ollama_ps_enabled() is False
    snap = residency_snapshot_from_ps("http://127.0.0.1:11434", budget_bytes=100)
    assert snap is not None
    assert snap["ps_disabled"] is True
    assert snap["models"] == []


def test_dashboard_ps_enabled_by_default(monkeypatch):
    monkeypatch.delenv("WORKER_DASHBOARD_OLLAMA_PS", raising=False)
    assert dashboard_ollama_ps_enabled() is True
