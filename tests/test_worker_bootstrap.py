import os

from worker import bootstrap


def test_suggest_memory_budget_uses_total_ram(monkeypatch):
    monkeypatch.setattr(bootstrap, "_total_memory_gb", lambda: 64.0)
    assert bootstrap.suggest_memory_budget_gb() == 56


def test_prompt_memory_budget_parses_gb(monkeypatch):
    monkeypatch.setattr(bootstrap, "_total_memory_gb", lambda: 32.0)
    monkeypatch.setattr(bootstrap, "_read_line", lambda _p: "24")
    assert bootstrap.prompt_memory_budget_gb() == 24.0


def test_prompt_model_mode_defaults_on_empty(monkeypatch):
    monkeypatch.setattr(bootstrap, "_read_line", lambda _p: "")
    assert bootstrap.prompt_model_mode(recommended="nano") == "nano"


def test_prompt_model_mode_rejects_invalid(monkeypatch):
    responses = iter(["invalid", "lite"])
    monkeypatch.setattr(bootstrap, "_read_line", lambda _p: next(responses))
    assert bootstrap.prompt_model_mode() == "lite"


def test_ensure_model_mode_persists_to_env_file(tmp_path, monkeypatch):
    env_path = tmp_path / "worker.env"
    monkeypatch.setattr(bootstrap, "default_env_path", lambda: env_path)
    monkeypatch.setattr(bootstrap, "_reload_annotation_models", lambda: None)
    mode = bootstrap.ensure_model_mode(env_path=env_path, interactive=False)
    assert mode == "performance"
    from shared.env_persist import load_env_file

    saved = load_env_file(env_path)
    assert saved["AUTOANNOTATION_MODEL_MODE"] == "performance"
    assert os.environ["AUTOANNOTATION_MODEL_MODE"] == "performance"


def test_bootstrap_writes_env_file(tmp_path, monkeypatch):
    env_path = tmp_path / "worker.env"
    monkeypatch.setattr(bootstrap, "default_env_path", lambda: env_path)
    monkeypatch.setattr(
        bootstrap,
        "_prompt_coordinator_url",
        lambda: "http://192.168.1.10:8000",
    )
    monkeypatch.setattr(bootstrap, "_prompt_token", lambda: "dev-token")
    monkeypatch.setattr(bootstrap, "prompt_memory_budget_gb", lambda: 24.0)
    monkeypatch.setattr(bootstrap, "ensure_model_mode", lambda **kwargs: "nano")
    monkeypatch.setattr(
        bootstrap.fleet_setup,
        "ensure_fleet_config",
        lambda **kwargs: bootstrap.fleet_setup.FleetConfig(
            num_servers=1,
            parallel=1,
            max_slots=1,
            w_all_bytes=2 * 1024**3,
            c_slot_bytes=int(0.4 * 1024**3),
        ),
    )
    bootstrap.ensure_worker_env(cli_overrides={}, interactive=True)
    from shared.env_persist import load_env_file

    saved = load_env_file(env_path)
    assert saved["COORDINATOR_URL"] == "http://192.168.1.10:8000"
    assert saved["WORKER_API_TOKEN"] == "dev-token"
    assert saved["ANNOTATION_MEMORY_BUDGET_GB"] == "24"


def test_ensure_worker_env_without_coordinator_uses_defaults(tmp_path, monkeypatch):
    env_path = tmp_path / "worker.env"
    monkeypatch.setattr(bootstrap, "default_env_path", lambda: env_path)
    monkeypatch.delenv("COORDINATOR_URL", raising=False)
    monkeypatch.delenv("WORKER_API_TOKEN", raising=False)
    monkeypatch.delenv("ANNOTATION_MEMORY_BUDGET_GB", raising=False)
    monkeypatch.setattr(bootstrap, "ensure_model_mode", lambda **kwargs: "performance")
    monkeypatch.setattr(
        bootstrap.fleet_setup,
        "ensure_fleet_config",
        lambda **kwargs: None,
    )

    def _should_not_prompt(*_a, **_k):
        raise AssertionError("prompt should not run when require_coordinator=False")

    monkeypatch.setattr(bootstrap, "_prompt_coordinator_url", _should_not_prompt)
    monkeypatch.setattr(bootstrap, "_prompt_token", _should_not_prompt)
    monkeypatch.setattr(bootstrap, "prompt_memory_budget_gb", _should_not_prompt)

    bootstrap.ensure_worker_env(
        interactive=False,
        require_coordinator=False,
        skip_fleet_config=True,
    )

    assert os.environ["COORDINATOR_URL"] == "http://127.0.0.1:9"
    assert os.environ["WORKER_API_TOKEN"] == "unused"
    assert os.environ["ANNOTATION_MEMORY_BUDGET_GB"] == "64"
