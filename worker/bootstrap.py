from __future__ import annotations

import os
import sys
from pathlib import Path

from shared.env_persist import load_env_file, resolve_value, save_env_file
from worker.fleet import setup as fleet_setup, sizing
from worker.probe import SystemSpec, probe_system


VALID_MODEL_MODES = ("performance", "lite", "nano")
DEFAULT_MODEL_MODE = "performance"
BUDGET_ENV_KEY = "WORKER_MODEL_MEMORY_BUDGET_GB"
LEGACY_BUDGET_ENV_KEY = "ANNOTATION_MEMORY_BUDGET_GB"


def default_env_path() -> Path:
    return Path(os.getenv("WORKER_ENV_FILE", "worker.env"))


def _read_line(prompt: str) -> str:
    print(prompt, end="", flush=True)
    return sys.stdin.readline()


def _format_memory_gb(value: float) -> str:
    if value == int(value):
        return str(int(value))
    return str(value)


def prompt_model_memory_budget_gb(spec: SystemSpec) -> float | None:
    ram_gb = spec.system_ram_bytes / (1024**3)
    vram_gb = sum(spec.vram_bytes) / (1024**3)
    suggested = sizing.effective_model_budget_bytes(spec, user_budget_gb=None) / (1024**3)
    prompt = (
        f"Machine RAM: {ram_gb:.0f} GB; VRAM: {vram_gb:.0f} GB. "
        f"Suggested model memory budget: {suggested:.0f} GB. "
        "Enter model memory budget in GB [-1 for max]: "
    )
    raw = _read_line(prompt).strip()
    return sizing.parse_model_memory_budget_gb(raw)


def resolve_model_memory_budget_gb(*, env_path: Path) -> tuple[str, float | None]:
    """Resolve the model budget, migrating the legacy env key when needed."""
    saved = load_env_file(env_path)
    raw = (
        os.getenv(BUDGET_ENV_KEY)
        or saved.get(BUDGET_ENV_KEY)
        or os.getenv(LEGACY_BUDGET_ENV_KEY)
        or saved.get(LEGACY_BUDGET_ENV_KEY)
    )
    if raw is None:
        raise KeyError(BUDGET_ENV_KEY)
    raw = str(raw).strip()
    budget_gb = sizing.parse_model_memory_budget_gb(raw)
    saved[BUDGET_ENV_KEY] = raw
    saved.pop(LEGACY_BUDGET_ENV_KEY, None)
    save_env_file(env_path, saved)
    return raw, budget_gb


def _prompt_coordinator_url() -> str:
    print(
        "Enter the coordinator's LAN URL (the machine running the coordinator service).",
        flush=True,
    )
    return _read_line("Coordinator URL (e.g. http://192.168.1.10:8000): ").strip()


def _prompt_token() -> str:
    return _read_line(
        "Worker API token (must match coordinator WORKER_API_TOKEN): "
    ).strip()


def prompt_model_mode(*, recommended: str = DEFAULT_MODEL_MODE) -> str:
    options = ", ".join(VALID_MODEL_MODES)
    while True:
        raw = _read_line(
            f"Annotation model mode [recommended: {recommended}] ({options}): "
        ).strip().lower()
        if not raw:
            return recommended
        if raw in VALID_MODEL_MODES:
            return raw
        print(f"Enter one of: {options}", flush=True)


def _reload_annotation_models() -> None:
    import importlib

    from autoannotation import models as ann_models
    from worker import ollama_bootstrap

    importlib.reload(ann_models)
    importlib.reload(ollama_bootstrap)


def ensure_model_mode(*, env_path: Path, interactive: bool = True) -> str:
    prompt_fn = None
    if interactive and sys.stdin.isatty():
        prompt_fn = lambda _key, default: prompt_model_mode(recommended=default or DEFAULT_MODEL_MODE)
    mode, _ = resolve_value(
        "AUTOANNOTATION_MODEL_MODE",
        env_file=env_path,
        cli_value=None,
        prompt_fn=prompt_fn,
        default=DEFAULT_MODEL_MODE,
    )
    normalized = mode.strip().lower()
    if normalized not in VALID_MODEL_MODES:
        raise ValueError(
            f"AUTOANNOTATION_MODEL_MODE must be one of {', '.join(VALID_MODEL_MODES)}"
        )
    os.environ["AUTOANNOTATION_MODEL_MODE"] = normalized
    _reload_annotation_models()
    return normalized


def ensure_worker_env(
    *,
    cli_overrides: dict | None = None,
    interactive: bool | None = None,
    skip_fleet_config: bool = False,
    require_coordinator: bool = True,
) -> None:
    cli_overrides = cli_overrides or {}
    path = default_env_path()
    is_interactive = sys.stdin.isatty() if interactive is None else interactive

    coord_default = None if require_coordinator else "http://127.0.0.1:9"
    token_default = None if require_coordinator else "unused"
    mem_default = None if require_coordinator else "64"

    url, _ = resolve_value(
        "COORDINATOR_URL",
        env_file=path,
        cli_value=cli_overrides.get("COORDINATOR_URL"),
        prompt_fn=(lambda _k, _d: _prompt_coordinator_url()) if is_interactive and require_coordinator else None,
        default=coord_default,
    )
    token, _ = resolve_value(
        "WORKER_API_TOKEN",
        env_file=path,
        cli_value=cli_overrides.get("WORKER_API_TOKEN"),
        prompt_fn=(lambda _k, _d: _prompt_token()) if is_interactive and require_coordinator else None,
        default=token_default,
    )

    mem = cli_overrides.get(BUDGET_ENV_KEY)
    if mem is not None:
        mem_str = _format_memory_gb(float(mem))
        saved = load_env_file(path)
        saved[BUDGET_ENV_KEY] = mem_str
        saved.pop(LEGACY_BUDGET_ENV_KEY, None)
        save_env_file(path, saved)
    else:
        try:
            mem_str, _ = resolve_model_memory_budget_gb(env_path=path)
        except KeyError:
            spec = probe_system()

            def _prompt_budget(_key: str, _default: str | None) -> str:
                budget_gb = prompt_model_memory_budget_gb(spec)
                return "-1" if budget_gb is None else _format_memory_gb(budget_gb)

            prompt_fn = (
                _prompt_budget if is_interactive and require_coordinator else None
            )
            mem_str, _ = resolve_value(
                BUDGET_ENV_KEY,
                env_file=path,
                cli_value=None,
                prompt_fn=prompt_fn,
                default=mem_default,
            )

    os.environ.setdefault("COORDINATOR_URL", url)
    os.environ.setdefault("WORKER_API_TOKEN", token)
    os.environ[BUDGET_ENV_KEY] = mem_str

    ensure_model_mode(env_path=path, interactive=is_interactive)
    if not skip_fleet_config:
        fleet_setup.ensure_fleet_config(interactive=is_interactive, env_path=path)
