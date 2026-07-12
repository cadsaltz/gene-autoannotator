from __future__ import annotations

import os
import sys
from pathlib import Path

from shared.env_persist import load_env_file, resolve_value, save_env_file
from worker.fleet import setup as fleet_setup


VALID_MODEL_MODES = ("performance", "lite", "nano")
DEFAULT_MODEL_MODE = "performance"


def default_env_path() -> Path:
    return Path(os.getenv("WORKER_ENV_FILE", "worker.env"))


def _total_memory_gb() -> float:
    try:
        import psutil

        return psutil.virtual_memory().total / (1024**3)
    except Exception:
        return 0.0


def suggest_memory_budget_gb() -> float:
    total = _total_memory_gb()
    if total <= 0:
        return 24.0
    return float(max(0, int(total - 8)))


def _read_line(prompt: str) -> str:
    print(prompt, end="", flush=True)
    return sys.stdin.readline()


def _format_memory_gb(value: float) -> str:
    if value == int(value):
        return str(int(value))
    return str(value)


def prompt_memory_budget_gb() -> float:
    total = _total_memory_gb()
    suggested = suggest_memory_budget_gb()
    prompt = (
        f"Machine RAM: {total:.0f} GB. "
        f"Suggested annotation budget: {suggested} GB. "
        f"Enter GB to dedicate [{suggested}]: "
    )
    raw = _read_line(prompt).strip()
    return float(raw or suggested)


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
) -> None:
    cli_overrides = cli_overrides or {}
    path = default_env_path()
    is_interactive = sys.stdin.isatty() if interactive is None else interactive

    url, _ = resolve_value(
        "COORDINATOR_URL",
        env_file=path,
        cli_value=cli_overrides.get("COORDINATOR_URL"),
        prompt_fn=lambda _k, _d: _prompt_coordinator_url(),
    )
    token, _ = resolve_value(
        "WORKER_API_TOKEN",
        env_file=path,
        cli_value=cli_overrides.get("WORKER_API_TOKEN"),
        prompt_fn=lambda _k, _d: _prompt_token(),
    )

    mem = cli_overrides.get("ANNOTATION_MEMORY_BUDGET_GB")
    if mem is not None:
        mem_str = _format_memory_gb(float(mem))
        saved = load_env_file(path)
        saved["ANNOTATION_MEMORY_BUDGET_GB"] = mem_str
        save_env_file(path, saved)
    else:
        mem_str, _ = resolve_value(
            "ANNOTATION_MEMORY_BUDGET_GB",
            env_file=path,
            cli_value=None,
            prompt_fn=lambda _k, _d: _format_memory_gb(prompt_memory_budget_gb()),
        )

    os.environ.setdefault("COORDINATOR_URL", url)
    os.environ.setdefault("WORKER_API_TOKEN", token)
    os.environ.setdefault("ANNOTATION_MEMORY_BUDGET_GB", mem_str)

    ensure_model_mode(env_path=path, interactive=is_interactive)
    if not skip_fleet_config:
        fleet_setup.ensure_fleet_config(interactive=is_interactive, env_path=path)
