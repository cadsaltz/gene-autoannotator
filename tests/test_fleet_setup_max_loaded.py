import os

from shared.env_persist import load_env_file


def test_bench_keep_alive_override_is_persisted(tmp_path, monkeypatch):
    from worker.bench import _persist_keep_alive_override

    env_path = tmp_path / "worker.env"
    env_path.write_text("OLLAMA_FLEET_KEEP_ALIVE=-1\n", encoding="utf-8")
    monkeypatch.delenv("OLLAMA_FLEET_KEEP_ALIVE", raising=False)
    monkeypatch.delenv("AUTOANNOTATION_OLLAMA_KEEP_ALIVE", raising=False)

    _persist_keep_alive_override("10m", env_path=env_path)

    assert load_env_file(env_path)["OLLAMA_FLEET_KEEP_ALIVE"] == "10m"
    assert os.environ["OLLAMA_FLEET_KEEP_ALIVE"] == "10m"
    assert os.environ["AUTOANNOTATION_OLLAMA_KEEP_ALIVE"] == "10m"
