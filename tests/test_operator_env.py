import os
from pathlib import Path

import pytest

from shared.env_persist import load_env_file
from worker.fleet import setup
from worker.fleet.sizing import FleetRecommendation
from worker.probe import SystemSpec


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


@pytest.mark.parametrize(
    ("key", "invalid"),
    [
        ("OLLAMA_FLEET_SLOT_CTX", "0"),
        ("OLLAMA_MAX_LOADED_MODELS", "not-an-int"),
        ("AUTOANNOTATION_SECTION_CHUNKING", "maybe"),
    ],
)
def test_ensure_operator_env_rejects_invalid_existing_values(
    tmp_path, key, invalid,
):
    env_path = tmp_path / "worker.env"
    env_path.write_text(f"{key}={invalid}\n", encoding="utf-8")

    with pytest.raises(ValueError, match=key):
        setup.ensure_operator_env(
            env_path=env_path, memory_tier="warm_stack", model_count=4,
        )


def test_pin_keep_alive_does_not_overwrite_existing_file_value(tmp_path, monkeypatch):
    env_path = tmp_path / "worker.env"
    env_path.write_text("OLLAMA_FLEET_KEEP_ALIVE=-1\n", encoding="utf-8")
    monkeypatch.setenv("OLLAMA_FLEET_KEEP_ALIVE", "0")

    setup._pin_keep_alive_from_environ(env_path)

    assert load_env_file(env_path)["OLLAMA_FLEET_KEEP_ALIVE"] == "-1"


def test_apply_fleet_keep_alive_does_not_use_tier_when_file_set(tmp_path, monkeypatch):
    """Simulate post-ensure: file keep-alive must survive a would-be tier default."""
    env_path = tmp_path / "worker.env"
    env_path.write_text(
        "\n".join(
            [
                "OLLAMA_FLEET_SERVERS=1",
                "OLLAMA_FLEET_PARALLEL=1",
                "WORKER_MAX_SLOTS=1",
                "OLLAMA_FLEET_KEEP_ALIVE=-1",
                "OLLAMA_FLEET_SLOT_CTX=2048",
                "OLLAMA_MAX_LOADED_MODELS=1",
                "AUTOANNOTATION_SECTION_CHUNKING=true",
                "OLLAMA_FLEET_W_ALL_BYTES=1000",
                "OLLAMA_FLEET_W_PEAK_BYTES=1000",
                "OLLAMA_FLEET_C_SLOT_BYTES=1",
                "OLLAMA_FLEET_MEMORY_TIER=vram_overflow",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("OLLAMA_FLEET_KEEP_ALIVE", "-1")

    setup.ensure_operator_env(
        env_path=env_path, memory_tier="vram_overflow", model_count=5,
    )

    assert os.environ["OLLAMA_FLEET_KEEP_ALIVE"] == "-1"
    assert os.environ["AUTOANNOTATION_OLLAMA_KEEP_ALIVE"] == "-1"


def test_first_fleet_bootstrap_materializes_operator_keep_alive_before_persist(
    tmp_path, monkeypatch,
):
    env_path = tmp_path / "worker.env"
    env_path.write_text("", encoding="utf-8")
    for key in (
        "OLLAMA_FLEET_KEEP_ALIVE",
        "AUTOANNOTATION_OLLAMA_KEEP_ALIVE",
        "OLLAMA_MAX_LOADED_MODELS",
    ):
        monkeypatch.delenv(key, raising=False)
    recommendation = FleetRecommendation(
        num_servers=1,
        parallel=1,
        max_slots=1,
        keep_alive="5m",
        w_all_bytes=1000,
        w_peak_bytes=1000,
        c_slot_bytes=1,
        memory_tier="warm_stack",
    )
    monkeypatch.setattr(setup.sizing, "recommend", lambda *args, **kwargs: recommendation)
    monkeypatch.setattr(setup.models, "estimate_w_all_bytes", lambda: 1000)
    monkeypatch.setattr(setup.models, "estimate_w_peak_bytes", lambda: 1000)
    monkeypatch.setattr(setup.models, "required_model_names", lambda: ["model"])
    spec = SystemSpec(
        gpu_count=1,
        vram_bytes=(10_000,),
        system_ram_bytes=10_000,
        cpu_physical=1,
        cpu_logical=1,
    )

    cfg = setup.ensure_fleet_config(
        spec=spec, interactive=False, env_path=env_path,
    )

    assert cfg.keep_alive == "0"
    assert load_env_file(env_path)["OLLAMA_FLEET_KEEP_ALIVE"] == "0"
