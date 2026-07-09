from worker.config import load_config


def test_load_config_uses_worker_max_slots_when_fleet_present(monkeypatch):
    monkeypatch.setenv("COORDINATOR_URL", "http://localhost:8000")
    monkeypatch.setenv("WORKER_API_TOKEN", "tok")
    monkeypatch.setenv("WORKER_MAX_SLOTS", "7")
    monkeypatch.setenv("OLLAMA_FLEET_SERVERS", "2")
    monkeypatch.setenv("OLLAMA_FLEET_PARALLEL", "3")
    monkeypatch.setenv("ANNOTATION_MEMORY_BUDGET_GB", "0")
    config = load_config()
    assert config.max_slots == 7


def test_load_config_falls_back_to_capacity_budget(monkeypatch):
    monkeypatch.setenv("COORDINATOR_URL", "http://localhost:8000")
    monkeypatch.setenv("WORKER_API_TOKEN", "tok")
    monkeypatch.delenv("WORKER_MAX_SLOTS", raising=False)
    monkeypatch.delenv("OLLAMA_FLEET_SERVERS", raising=False)
    monkeypatch.delenv("OLLAMA_FLEET_PARALLEL", raising=False)
    monkeypatch.setenv("ANNOTATION_MEMORY_BUDGET_GB", "42")
    config = load_config()
    assert config.max_slots == 1
