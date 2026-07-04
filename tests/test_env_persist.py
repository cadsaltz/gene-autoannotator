from pathlib import Path

from shared.env_persist import load_env_file, resolve_value, save_env_file


def test_load_and_save_round_trip(tmp_path):
    path = tmp_path / "test.env"
    save_env_file(path, {"COORDINATOR_URL": "http://a:8000", "WORKER_API_TOKEN": "tok"})
    assert load_env_file(path) == {
        "COORDINATOR_URL": "http://a:8000",
        "WORKER_API_TOKEN": "tok",
    }


def test_resolve_prefers_cli_over_env_file(tmp_path, monkeypatch):
    path = tmp_path / "test.env"
    save_env_file(path, {"COORDINATOR_URL": "http://file:8000"})
    monkeypatch.delenv("COORDINATOR_URL", raising=False)
    value, source = resolve_value(
        "COORDINATOR_URL",
        env_file=path,
        cli_value="http://cli:8000",
        prompt_fn=lambda _k, _d: "http://prompt:8000",
    )
    assert value == "http://cli:8000"
    assert source == "cli"
    assert load_env_file(path)["COORDINATOR_URL"] == "http://cli:8000"


def test_resolve_prompts_when_missing(tmp_path, monkeypatch):
    path = tmp_path / "test.env"
    monkeypatch.delenv("COORDINATOR_URL", raising=False)
    value, source = resolve_value(
        "COORDINATOR_URL",
        env_file=path,
        cli_value=None,
        prompt_fn=lambda _k, default: default or "http://prompt:8000",
        default="http://default:8000",
    )
    assert value == "http://default:8000"
    assert source == "default"
    assert load_env_file(path)["COORDINATOR_URL"] == "http://default:8000"
