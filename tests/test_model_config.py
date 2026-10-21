import importlib

from autoannotation import models
from worker import ollama_bootstrap


def reload_models(monkeypatch, **env):
    for key in (
        "AUTOANNOTATION_MODEL_MODE",
        "AUTOANNOTATION_SUMMARY_MODELS",
        "AUTOANNOTATION_CONSENSUS_MODEL",
        "AUTOANNOTATION_AGGREGATION_MODEL",
        "AUTOANNOTATION_REGEX_MODEL",
    ):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return importlib.reload(models)


def test_model_config_defaults_to_gemma4_solo(monkeypatch):
    configured = reload_models(monkeypatch)

    assert configured.MODEL_SUMMARY == ["gemma4:12b"]
    assert configured.MODEL_CONSENSUS == "qwen3:8b"
    assert configured.MODEL_AGGREGATION == "gemma3:27b"
    assert configured.MODEL_REGEX == "gemma4:12b"
    assert configured.uses_section_consensus() is False
    assert configured.section_distillation_model_name() == "gemma4:12b"


def test_model_config_can_use_lite_mode(monkeypatch):
    configured = reload_models(monkeypatch, AUTOANNOTATION_MODEL_MODE="lite")

    assert configured.MODEL_SUMMARY == [
        "qwen3.5:0.8b",
        "gemma3:1b",
        "llama3.2:1b",
    ]
    assert configured.MODEL_CONSENSUS == "qwen3:0.6b"
    assert configured.MODEL_AGGREGATION == "qwen3:1.7b"
    assert configured.uses_section_consensus() is True


def test_model_config_can_use_nano_mode(monkeypatch):
    configured = reload_models(monkeypatch, AUTOANNOTATION_MODEL_MODE="nano")

    assert configured.MODEL_SUMMARY == [
        "qwen3:0.6b",
        "qwen2.5:0.5b",
        "gemma3:270m",
    ]
    assert configured.MODEL_CONSENSUS == "gemma3:270m"
    assert configured.MODEL_AGGREGATION == "gemma3:1b"


def test_model_config_accepts_a_single_override_model(monkeypatch):
    configured = reload_models(
        monkeypatch,
        AUTOANNOTATION_SUMMARY_MODELS="gemma4:12b",
        AUTOANNOTATION_CONSENSUS_MODEL="qwen3:8b",
        AUTOANNOTATION_AGGREGATION_MODEL="gemma3:27b",
    )

    assert configured.MODEL_SUMMARY == ["gemma4:12b"]
    assert configured.uses_section_consensus() is False


def test_model_config_can_be_overridden_by_environment(monkeypatch):
    configured = reload_models(
        monkeypatch,
        AUTOANNOTATION_SUMMARY_MODELS=(
            "mistral:7b-instruct-v0.2-q3_K_M,gemma3:4b"
        ),
        AUTOANNOTATION_CONSENSUS_MODEL="qwen3:8b",
        AUTOANNOTATION_AGGREGATION_MODEL="gemma3:4b",
    )

    assert configured.MODEL_SUMMARY == [
        "mistral:7b-instruct-v0.2-q3_K_M",
        "gemma3:4b",
    ]
    assert configured.MODEL_CONSENSUS == "qwen3:8b"
    assert configured.MODEL_AGGREGATION == "gemma3:4b"
    assert configured.uses_section_consensus() is True
    assert configured.section_distillation_model_name() == "qwen3:8b"


def test_regex_model_defaults_to_consensus_when_multi_extractor(monkeypatch):
    configured = reload_models(
        monkeypatch,
        AUTOANNOTATION_SUMMARY_MODELS="qwen3:14b,gemma3:12b",
    )

    assert configured.MODEL_REGEX == configured.MODEL_CONSENSUS


def test_regex_model_can_be_overridden(monkeypatch):
    configured = reload_models(monkeypatch, AUTOANNOTATION_REGEX_MODEL="qwen2.5:7b-instruct")

    assert configured.MODEL_REGEX == "qwen2.5:7b-instruct"


def test_required_models_skips_unused_consensus_on_solo(monkeypatch):
    reload_models(monkeypatch)
    importlib.reload(ollama_bootstrap)

    required = ollama_bootstrap.required_models()
    assert required == {"gemma4:12b", "gemma3:27b"}


def test_required_models_includes_consensus_when_multi_extractor(monkeypatch):
    reload_models(
        monkeypatch,
        AUTOANNOTATION_SUMMARY_MODELS="qwen3:14b,gemma3:12b",
        AUTOANNOTATION_CONSENSUS_MODEL="qwen3:8b",
        AUTOANNOTATION_AGGREGATION_MODEL="gemma3:27b",
    )
    importlib.reload(ollama_bootstrap)

    required = ollama_bootstrap.required_models()
    assert "qwen3:8b" in required
    assert "qwen3:14b" in required
    assert "gemma3:12b" in required
    assert "gemma3:27b" in required
