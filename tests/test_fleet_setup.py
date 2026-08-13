import pytest

from worker.fleet.config import FleetConfig
from worker.fleet import setup


def test_build_ollama_server_env_uses_slot_ctx_times_parallel(monkeypatch):
    monkeypatch.setenv("OLLAMA_HOST", "http://127.0.0.1:11434")
    monkeypatch.setenv("OLLAMA_FLEET_SLOT_CTX", "8192")
    monkeypatch.setenv("OLLAMA_CONTEXT_LENGTH", "99999")  # must be ignored
    env = setup._build_ollama_server_env(port=11435, parallel=2, gpu_index=0)
    assert env["OLLAMA_CONTEXT_LENGTH"] == "16384"


def test_effective_ollama_context_length_requires_slot_ctx(monkeypatch):
    monkeypatch.delenv("OLLAMA_FLEET_SLOT_CTX", raising=False)
    monkeypatch.delenv("OLLAMA_CONTEXT_LENGTH", raising=False)
    with pytest.raises(ValueError, match="OLLAMA_FLEET_SLOT_CTX"):
        setup.effective_ollama_context_length(parallel=2)


def test_effective_ollama_context_length_scales_with_parallel(monkeypatch):
    monkeypatch.setenv("OLLAMA_FLEET_SLOT_CTX", "8192")
    monkeypatch.setenv("OLLAMA_CONTEXT_LENGTH", "1")  # ignored
    assert setup.effective_ollama_context_length(parallel=2) == 16384
    assert setup.effective_ollama_context_length(parallel=1) == 8192


def test_effective_max_loaded_models_requires_env(monkeypatch):
    monkeypatch.delenv("OLLAMA_MAX_LOADED_MODELS", raising=False)
    cfg = FleetConfig(
        num_servers=1, parallel=1, max_slots=1,
        memory_tier="warm_stack", model_count=4,
    )
    with pytest.raises(ValueError, match="OLLAMA_MAX_LOADED_MODELS"):
        setup.effective_max_loaded_models(cfg)


def test_effective_max_loaded_models_reads_env(monkeypatch):
    monkeypatch.setenv("OLLAMA_MAX_LOADED_MODELS", "2")
    cfg = FleetConfig(num_servers=1, parallel=1, max_slots=1, memory_tier="swap")
    assert setup.effective_max_loaded_models(cfg) == 2
