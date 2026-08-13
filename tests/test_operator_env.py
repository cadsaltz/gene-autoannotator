import os
from pathlib import Path

from shared.env_persist import load_env_file
from worker.fleet import setup


def test_ensure_operator_env_writes_defaults_once(tmp_path, monkeypatch):
    env_path = tmp_path / "worker.env"
    env_path.write_text("COORDINATOR_URL=http://x\n", encoding="utf-8")
    monkeypatch.delenv("OLLAMA_FLEET_SLOT_CTX", raising=False)
    monkeypatch.delenv("OLLAMA_FLEET_KEEP_ALIVE", raising=False)
    monkeypatch.delenv("OLLAMA_MAX_LOADED_MODELS", raising=False)
    monkeypatch.delenv("AUTOANNOTATION_SECTION_CHUNKING", raising=False)

    setup.ensure_operator_env(
        env_path=env_path, memory_tier="vram_overflow", model_count=5,
    )
    saved = load_env_file(env_path)
    assert saved["OLLAMA_FLEET_SLOT_CTX"] == "8192"
    assert saved["OLLAMA_FLEET_KEEP_ALIVE"] == "0"
    assert saved["OLLAMA_MAX_LOADED_MODELS"] == "1"
    assert saved["AUTOANNOTATION_SECTION_CHUNKING"] == "true"
    assert os.environ["AUTOANNOTATION_OLLAMA_KEEP_ALIVE"] == "0"

    env_path.write_text(
        "\n".join(
            [
                "COORDINATOR_URL=http://x",
                "OLLAMA_FLEET_SLOT_CTX=2048",
                "OLLAMA_FLEET_KEEP_ALIVE=-1",
                "OLLAMA_MAX_LOADED_MODELS=3",
                "AUTOANNOTATION_SECTION_CHUNKING=false",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    setup.ensure_operator_env(
        env_path=env_path, memory_tier="warm_stack", model_count=5,
    )
    saved = load_env_file(env_path)
    assert saved["OLLAMA_FLEET_SLOT_CTX"] == "2048"
    assert saved["OLLAMA_FLEET_KEEP_ALIVE"] == "-1"
    assert saved["OLLAMA_MAX_LOADED_MODELS"] == "3"
    assert saved["AUTOANNOTATION_SECTION_CHUNKING"] == "false"
    assert os.environ["AUTOANNOTATION_OLLAMA_KEEP_ALIVE"] == "-1"


def test_ensure_operator_env_max_loaded_warm_stack(tmp_path, monkeypatch):
    env_path = tmp_path / "worker.env"
    env_path.write_text("", encoding="utf-8")
    monkeypatch.delenv("OLLAMA_MAX_LOADED_MODELS", raising=False)
    setup.ensure_operator_env(
        env_path=env_path, memory_tier="warm_stack", model_count=4,
    )
    assert load_env_file(env_path)["OLLAMA_MAX_LOADED_MODELS"] == "4"
