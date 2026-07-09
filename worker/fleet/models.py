from __future__ import annotations

import json
import logging
import subprocess
from typing import Iterable

from worker.ollama_bootstrap import required_models

log = logging.getLogger(__name__)


def required_model_names() -> list[str]:
    return sorted(required_models())


def _model_size_bytes(model_name: str) -> int:
    result = subprocess.run(
        ["ollama", "show", model_name, "--json"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ollama show failed for {model_name}: {result.stderr}")
    payload = json.loads(result.stdout)
    for key in ("size", "size_vram"):
        if payload.get(key):
            return int(payload[key])
    return int(payload.get("details", {}).get("parameter_size", 0) or 0)


def estimate_w_all_bytes(model_names: Iterable[str] | None = None) -> int:
    names = list(model_names or required_model_names())
    return sum(_model_size_bytes(name) for name in names)


def measure_w_all_bytes(host: str = "http://127.0.0.1:11434") -> int:
    """Warm all models on host, then sum size_vram from `ollama ps`."""
    import ollama

    client = ollama.Client(host=host)
    for name in required_model_names():
        client.chat(
            model=name,
            messages=[{"role": "user", "content": "ping"}],
            keep_alive="5m",
        )
    ps = client.ps()
    entries = ps.get("models", []) if isinstance(ps, dict) else getattr(ps, "models", [])
    total = 0
    for entry in entries:
        if isinstance(entry, dict):
            total += int(entry.get("size_vram") or entry.get("size") or 0)
        else:
            total += int(
                getattr(entry, "size_vram", 0) or getattr(entry, "size", 0) or 0
            )
    log.info("Measured W_all on %s: %.2f GB", host, total / (1024**3))
    return total
