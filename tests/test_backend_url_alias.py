import os

from worker.env_urls import resolve_backend_url


def test_backend_url_prefers_backend_over_coordinator(monkeypatch):
    monkeypatch.setenv("BACKEND_URL", "https://api.example/backend")
    monkeypatch.setenv("COORDINATOR_URL", "http://legacy:8000")
    assert resolve_backend_url() == "https://api.example/backend"


def test_backend_url_falls_back_to_coordinator(monkeypatch):
    monkeypatch.delenv("BACKEND_URL", raising=False)
    monkeypatch.setenv("COORDINATOR_URL", "http://legacy:8000")
    assert resolve_backend_url() == "http://legacy:8000"


def test_worker_config_uses_backend_url(monkeypatch):
    from worker import config as worker_config

    monkeypatch.setenv("BACKEND_URL", "https://api.example/backend/")
    monkeypatch.setenv("COORDINATOR_URL", "http://legacy:8000")
    monkeypatch.delenv("OLLAMA_FLEET_SERVERS", raising=False)
    monkeypatch.delenv("OLLAMA_FLEET_PARALLEL", raising=False)
    monkeypatch.setattr(worker_config, "probe_system", lambda: None)
    monkeypatch.setattr(worker_config, "_total_memory_bytes", lambda: 0)
    monkeypatch.setattr(
        worker_config.sizing, "effective_model_budget_bytes", lambda *_args, **_kwargs: 0
    )

    config = worker_config.load_config()

    assert config.coordinator_url == "https://api.example/backend"


def test_worker_bootstrap_accepts_backend_url(tmp_path, monkeypatch):
    from worker import bootstrap

    env_path = tmp_path / "worker.env"
    env_path.write_text("BACKEND_URL=https://api.example/backend\n", encoding="utf-8")
    monkeypatch.setattr(bootstrap, "default_env_path", lambda: env_path)
    monkeypatch.delenv("BACKEND_URL", raising=False)
    monkeypatch.delenv("COORDINATOR_URL", raising=False)
    monkeypatch.setenv("WORKER_API_TOKEN", "token")
    monkeypatch.setenv("WORKER_MODEL_MEMORY_BUDGET_GB", "64")
    monkeypatch.setattr(bootstrap, "ensure_model_mode", lambda **_kwargs: "performance")

    bootstrap.ensure_worker_env(
        interactive=False,
        skip_fleet_config=True,
    )

    coordinator_url = os.environ.pop("COORDINATOR_URL")
    assert coordinator_url == "https://api.example/backend"


def test_worker_bootstrap_cli_url_overrides_backend_env(tmp_path, monkeypatch):
    from worker import bootstrap
    from worker import config as worker_config

    env_path = tmp_path / "worker.env"
    monkeypatch.setattr(bootstrap, "default_env_path", lambda: env_path)
    monkeypatch.setenv("BACKEND_URL", "https://backend-a.example")
    monkeypatch.setenv("COORDINATOR_URL", "https://coordinator-a.example")
    monkeypatch.setenv("WORKER_API_TOKEN", "token")
    monkeypatch.setenv("WORKER_MODEL_MEMORY_BUDGET_GB", "64")
    monkeypatch.setattr(bootstrap, "ensure_model_mode", lambda **_kwargs: "performance")
    monkeypatch.delenv("OLLAMA_FLEET_SERVERS", raising=False)
    monkeypatch.delenv("OLLAMA_FLEET_PARALLEL", raising=False)
    monkeypatch.setattr(worker_config, "probe_system", lambda: None)
    monkeypatch.setattr(worker_config, "_total_memory_bytes", lambda: 0)
    monkeypatch.setattr(
        worker_config.sizing, "effective_model_budget_bytes", lambda *_args, **_kwargs: 0
    )

    bootstrap.ensure_worker_env(
        cli_overrides={"COORDINATOR_URL": "https://backend-b.example/"},
        interactive=False,
        skip_fleet_config=True,
    )

    assert resolve_backend_url() == "https://backend-b.example"
    assert worker_config.load_config().coordinator_url == "https://backend-b.example"
