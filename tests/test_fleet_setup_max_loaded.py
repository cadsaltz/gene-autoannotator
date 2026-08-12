from worker.fleet.config import FleetConfig
from worker.fleet import setup


def test_effective_max_loaded_models_allows_full_stack_on_overflow(monkeypatch):
    monkeypatch.delenv("OLLAMA_MAX_LOADED_MODELS", raising=False)
    cfg = FleetConfig(
        num_servers=1,
        parallel=2,
        max_slots=2,
        memory_tier="vram_overflow",
        model_count=5,
    )
    assert setup.effective_max_loaded_models(cfg) == 5


def test_effective_max_loaded_models_uses_model_count_for_swap(monkeypatch):
    monkeypatch.delenv("OLLAMA_MAX_LOADED_MODELS", raising=False)
    cfg = FleetConfig(
        num_servers=1,
        parallel=1,
        max_slots=1,
        memory_tier="swap",
        model_count=4,
    )
    assert setup.effective_max_loaded_models(cfg) == 4


def test_effective_max_loaded_models_uses_model_count_for_warm_stack(monkeypatch):
    monkeypatch.delenv("OLLAMA_MAX_LOADED_MODELS", raising=False)
    cfg = FleetConfig(
        num_servers=1,
        parallel=1,
        max_slots=1,
        memory_tier="warm_stack",
        model_count=4,
    )
    assert setup.effective_max_loaded_models(cfg) == 4


def test_effective_max_loaded_models_respects_env_override(monkeypatch):
    monkeypatch.setenv("OLLAMA_MAX_LOADED_MODELS", "2")
    cfg = FleetConfig(num_servers=1, parallel=1, max_slots=1, memory_tier="swap")
    assert setup.effective_max_loaded_models(cfg) == 2
