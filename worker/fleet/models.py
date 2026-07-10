from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import urllib.error
import urllib.request
from typing import Iterable

from worker.ollama_bootstrap import required_models

log = logging.getLogger(__name__)

_SIZE_TOKEN = re.compile(
    r"^([\d.]+)\s*(B|KB|MB|GB|TB)?$",
    re.IGNORECASE,
)

# Warm-stack VRAM estimates when Ollama size probes are unavailable (pre-start).
_MODE_W_ALL_ESTIMATE_BYTES = {
    "nano": int(2 * 1024**3),
    "lite": int(4 * 1024**3),
    "performance": int(52 * 1024**3),
}

_MODE_W_PEAK_ESTIMATE_BYTES = {
    "nano": int(1.2 * 1024**3),
    "lite": int(1.7 * 1024**3),
    "performance": int(16 * 1024**3),
}

_SIZE_MULTIPLIERS = {
    "B": 1,
    "KB": 1024,
    "MB": 1024**2,
    "GB": 1024**3,
    "TB": 1024**4,
}


def required_model_names() -> list[str]:
    return sorted(required_models())


def _parse_size_token(raw: str) -> int | None:
    match = _SIZE_TOKEN.match(raw.strip())
    if not match:
        return None
    value = float(match.group(1))
    unit = (match.group(2) or "B").upper()
    return int(value * _SIZE_MULTIPLIERS[unit])


def _size_from_show_json(model_name: str) -> int | None:
    result = subprocess.run(
        ["ollama", "show", model_name, "--json"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        if "unknown flag" in stderr.lower():
            return None
        return None
    payload = json.loads(result.stdout)
    for key in ("size", "size_vram"):
        if payload.get(key):
            return int(payload[key])
    details = payload.get("details") or {}
    if details.get("parameter_size"):
        return int(details["parameter_size"])
    return None


def _size_from_ollama_list_text(model_name: str, listing: str) -> int | None:
    base_name = model_name.split(":")[0]
    tag = model_name.split(":", 1)[1] if ":" in model_name else "latest"
    for line in listing.splitlines()[1:]:
        if not line.strip():
            continue
        parts = line.split()
        if len(parts) < 3:
            continue
        name = parts[0]
        if len(parts) > 3 and parts[3].upper() in _SIZE_MULTIPLIERS:
            size_token = f"{parts[2]} {parts[3]}"
        else:
            size_token = parts[2]
        if name == model_name:
            return _parse_size_token(size_token)
        if ":" not in name and name == base_name and tag == "latest":
            return _parse_size_token(size_token)
    return None


def _size_from_ollama_list(model_name: str) -> int | None:
    result = subprocess.run(
        ["ollama", "list"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    return _size_from_ollama_list_text(model_name, result.stdout)


def _size_from_show_api(model_name: str, host: str = "http://127.0.0.1:11434") -> int | None:
    payload = json.dumps({"model": model_name}).encode("utf-8")
    request = urllib.request.Request(
        f"{host.rstrip('/')}/api/show",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            body = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return None
    for key in ("size", "size_vram"):
        if body.get(key):
            return int(body[key])
    details = body.get("details") or {}
    if isinstance(details, dict) and details.get("parameter_size"):
        return int(details["parameter_size"])
    return None


def _mode_stack_estimate_bytes() -> int:
    mode = os.getenv("AUTOANNOTATION_MODEL_MODE", "performance").strip().lower()
    return _MODE_W_ALL_ESTIMATE_BYTES.get(mode, _MODE_W_ALL_ESTIMATE_BYTES["performance"])


def _per_model_fallback_bytes(model_names: list[str]) -> int:
    if not model_names:
        return _mode_stack_estimate_bytes()
    return max(1, _mode_stack_estimate_bytes() // len(model_names))


def _model_size_bytes(model_name: str) -> int:
    for probe in (
        lambda: _size_from_ollama_list(model_name),
        lambda: _size_from_show_json(model_name),
        lambda: _size_from_show_api(model_name),
    ):
        try:
            size = probe()
        except Exception as exc:  # noqa: BLE001 - try next probe
            log.debug("Model size probe failed for %s: %s", model_name, exc)
            size = None
        if size and size > 0:
            return size
    fallback = _per_model_fallback_bytes([model_name])
    log.warning(
        "Could not probe size for %s; using mode fallback %.2f GB",
        model_name,
        fallback / (1024**3),
    )
    return fallback


def _mode_peak_estimate_bytes() -> int:
    mode = os.getenv("AUTOANNOTATION_MODEL_MODE", "performance").strip().lower()
    return _MODE_W_PEAK_ESTIMATE_BYTES.get(mode, _MODE_W_PEAK_ESTIMATE_BYTES["performance"])


def estimate_w_peak_bytes(model_names: Iterable[str] | None = None) -> int:
    """Largest single model footprint (bytes) for request-based / swap sizing."""
    names = list(model_names or required_model_names())
    if not names:
        return _mode_peak_estimate_bytes()
    sizes = [_model_size_bytes(name) for name in names]
    peak = max(sizes) if sizes else 0
    if peak <= 0:
        peak = _mode_peak_estimate_bytes()
        log.warning(
            "Using mode peak estimate for W_peak: %.2f GB (mode=%s)",
            peak / (1024**3),
            os.getenv("AUTOANNOTATION_MODEL_MODE", "performance"),
        )
    return peak


def estimate_w_all_bytes(model_names: Iterable[str] | None = None) -> int:
    names = list(model_names or required_model_names())
    if not names:
        return _mode_stack_estimate_bytes()
    sizes = [_model_size_bytes(name) for name in names]
    total = sum(sizes)
    if total <= 0:
        total = _mode_stack_estimate_bytes()
        log.warning(
            "Using mode stack estimate for W_all: %.2f GB (mode=%s)",
            total / (1024**3),
            os.getenv("AUTOANNOTATION_MODEL_MODE", "performance"),
        )
    return total


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
