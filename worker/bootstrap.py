from __future__ import annotations

import os
import sys
from pathlib import Path

from shared.env_persist import load_env_file, resolve_value, save_env_file


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


def ensure_worker_env(*, cli_overrides: dict | None = None) -> None:
    cli_overrides = cli_overrides or {}
    path = default_env_path()

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
