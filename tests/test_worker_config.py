from worker import config as worker_config
from worker.config import load_config
from worker.probe import SystemSpec


def test_load_config_uses_worker_max_slots_when_fleet_present(monkeypatch):
    monkeypatch.setenv("COORDINATOR_URL", "http://localhost:8000")
    monkeypatch.setenv("WORKER_API_TOKEN", "tok")
    monkeypatch.setenv("WORKER_MAX_SLOTS", "7")
    monkeypatch.setenv("OLLAMA_FLEET_SERVERS", "2")
    monkeypatch.setenv("OLLAMA_FLEET_PARALLEL", "3")
    monkeypatch.setenv("WORKER_MODEL_MEMORY_BUDGET_GB", "0")
    config = load_config()
    assert config.max_slots == 7


def test_load_config_falls_back_to_capacity_budget(monkeypatch):
    spec = SystemSpec(
        gpu_count=1,
        vram_bytes=(8 * 1024**3,),
        system_ram_bytes=128 * 1024**3,
        cpu_physical=6,
        cpu_logical=12,
    )
    monkeypatch.setenv("COORDINATOR_URL", "http://localhost:8000")
    monkeypatch.setenv("WORKER_API_TOKEN", "tok")
    monkeypatch.delenv("WORKER_MAX_SLOTS", raising=False)
    monkeypatch.delenv("OLLAMA_FLEET_SERVERS", raising=False)
    monkeypatch.delenv("OLLAMA_FLEET_PARALLEL", raising=False)
    monkeypatch.setenv("WORKER_MODEL_MEMORY_BUDGET_GB", "42")
    monkeypatch.setattr(worker_config, "probe_system", lambda: spec)
    config = load_config()
    assert config.max_slots == 1


def test_load_config_dedicated_bytes_uses_effective_budget(monkeypatch):
    spec = SystemSpec(
        gpu_count=1,
        vram_bytes=(8 * 1024**3,),
        system_ram_bytes=32 * 1024**3,
        cpu_physical=6,
        cpu_logical=12,
    )
    monkeypatch.setenv("COORDINATOR_URL", "http://127.0.0.1:8000")
    monkeypatch.setenv("WORKER_MODEL_MEMORY_BUDGET_GB", "16")
    monkeypatch.setenv("OLLAMA_FLEET_SERVERS", "1")
    monkeypatch.setenv("OLLAMA_FLEET_PARALLEL", "2")
    monkeypatch.setenv("WORKER_MAX_SLOTS", "3")
    monkeypatch.setattr(worker_config, "probe_system", lambda: spec)

    loaded = load_config()

    assert loaded.dedicated_memory_bytes == 16 * 1024**3
    assert loaded.max_slots == 3
