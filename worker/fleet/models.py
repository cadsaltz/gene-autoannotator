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


def _host_to_ollama_env(host: str) -> str:
    return host.removeprefix("http://").removeprefix("https://").rstrip("/")


def _size_from_show_text(model_name: str, *, host: str | None = None) -> int | None:
    env = os.environ.copy()
    if host:
        env["OLLAMA_HOST"] = _host_to_ollama_env(host)
    result = subprocess.run(
        ["ollama", "show", model_name],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    if result.returncode != 0:
        return None
    for line in result.stdout.splitlines():
        stripped = line.strip()
        lower = stripped.lower()
        if lower.startswith("size") and "\t" in stripped:
            _, raw = stripped.split("\t", 1)
            parsed = _parse_size_token(raw.strip())
            if parsed:
                return parsed
        if "parameter size" in lower or lower.startswith("parameters"):
            continue
    return None


def _size_from_ollama_list(model_name: str, *, host: str | None = None) -> int | None:
    env = os.environ.copy()
    if host:
        env["OLLAMA_HOST"] = _host_to_ollama_env(host)
    result = subprocess.run(
        ["ollama", "list"],
        check=False,
        capture_output=True,
        text=True,
        env=env,
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


def _per_model_fallback_bytes() -> int:
    count = max(1, len(required_model_names()))
    return max(1, _mode_stack_estimate_bytes() // count)


def _probe_model_size_bytes(model_name: str, *, host: str | None = None) -> int | None:
    for probe in (
        lambda: _size_from_show_api(model_name, host=host) if host else _size_from_show_api(model_name),
        lambda: _size_from_ollama_list(model_name, host=host),
        lambda: _size_from_show_text(model_name, host=host),
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
    return None


def _model_size_bytes(model_name: str, *, host: str | None = None, warn: bool = False) -> int:
    size = _probe_model_size_bytes(model_name, host=host)
    if size:
        return size
    fallback = _per_model_fallback_bytes()
    if warn:
        log.warning(
            "Could not probe size for %s; using mode fallback %.2f GB",
            model_name,
            fallback / (1024**3),
        )
    else:
        log.debug(
            "Could not probe size for %s; using mode fallback %.2f GB",
            model_name,
            fallback / (1024**3),
        )
    return fallback


def manifest_model_sizes(*, host: str) -> dict[str, int]:
    """Read on-disk / manifest sizes from a running Ollama host."""
    sizes: dict[str, int] = {}
    for name in required_model_names():
        size = _probe_model_size_bytes(name, host=host)
        if size:
            sizes[name] = size
    return sizes


def measure_w_peak_runtime(host: str) -> int:
    """Load each model in turn (keep_alive=0) and return max VRAM from `ollama ps`."""
    import ollama

    client = ollama.Client(host=host)
    peak = 0
    for name in required_model_names():
        client.chat(
            model=name,
            messages=[{"role": "user", "content": "ping"}],
            keep_alive=0,
        )
        ps = client.ps()
        entries = ps.get("models", []) if isinstance(ps, dict) else getattr(ps, "models", [])
        for entry in entries:
            if isinstance(entry, dict):
                value = int(entry.get("size_vram") or entry.get("size") or 0)
            else:
                value = int(
                    getattr(entry, "size_vram", 0) or getattr(entry, "size", 0) or 0
                )
            peak = max(peak, value)
    log.info("Measured W_peak runtime on %s: %.2f GB", host, peak / (1024**3))
    return peak


def resolve_footprints(
    *,
    host: str | None = None,
    measure_runtime_peak: bool = False,
) -> tuple[int, int, str]:
    """Return (w_all_bytes, w_peak_bytes, source).

    source is one of: manifest, runtime, estimate
    """
    names = required_model_names()
    if host:
        manifest = manifest_model_sizes(host=host)
        if len(manifest) == len(names):
            w_all = sum(manifest.values())
            w_peak = max(manifest.values())
            source = "manifest"
            if measure_runtime_peak:
                try:
                    runtime_peak = measure_w_peak_runtime(host)
                    if runtime_peak > 0:
                        w_peak = runtime_peak
                        source = "runtime"
                except Exception as exc:  # noqa: BLE001
                    log.warning("Runtime W_peak measurement failed on %s: %s", host, exc)
            log.info(
                "Resolved footprints from %s on %s: W_all=%.2f GB W_peak=%.2f GB",
                source,
                host,
                w_all / (1024**3),
                w_peak / (1024**3),
            )
            return w_all, w_peak, source

    w_all = estimate_w_all_bytes()
    w_peak = estimate_w_peak_bytes()
    log.info(
        "Using mode footprint estimates (Ollama not ready): W_all=%.2f GB W_peak=%.2f GB",
        w_all / (1024**3),
        w_peak / (1024**3),
    )
    return w_all, w_peak, "estimate"


def _mode_peak_estimate_bytes() -> int:
    mode = os.getenv("AUTOANNOTATION_MODEL_MODE", "performance").strip().lower()
    return _MODE_W_PEAK_ESTIMATE_BYTES.get(mode, _MODE_W_PEAK_ESTIMATE_BYTES["performance"])


def estimate_w_peak_bytes(model_names: Iterable[str] | None = None) -> int:
    """Largest single model footprint (bytes) for request-based / swap sizing."""
    names = list(model_names or required_model_names())
    if not names:
        return _mode_peak_estimate_bytes()
    sizes = [_model_size_bytes(name, warn=False) for name in names]
    peak = max(sizes) if sizes else 0
    if peak <= 0:
        peak = _mode_peak_estimate_bytes()
        log.debug(
            "Using mode peak estimate for W_peak: %.2f GB (mode=%s)",
            peak / (1024**3),
            os.getenv("AUTOANNOTATION_MODEL_MODE", "performance"),
        )
    return peak


def estimate_w_all_bytes(model_names: Iterable[str] | None = None) -> int:
    names = list(model_names or required_model_names())
    if not names:
        return _mode_stack_estimate_bytes()
    sizes = [_model_size_bytes(name, warn=False) for name in names]
    total = sum(sizes)
    if total <= 0:
        total = _mode_stack_estimate_bytes()
        log.debug(
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
