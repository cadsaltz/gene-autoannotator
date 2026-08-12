"""Ollama ``/api/ps`` helpers for dashboard residency (optional, cached probe)."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request
from typing import Any

log = logging.getLogger(__name__)

DASHBOARD_PS_ENV = "WORKER_DASHBOARD_OLLAMA_PS"
DASHBOARD_PS_INTERVAL_ENV = "WORKER_DASHBOARD_OLLAMA_PS_INTERVAL_SEC"
DEFAULT_PS_INTERVAL_SEC = 5.0
DEFAULT_PS_TIMEOUT_SEC = 0.5

_cache_lock = threading.Lock()
# host -> (monotonic_ts, residents list)
_ps_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}


def dashboard_ollama_ps_enabled() -> bool:
    raw = (os.getenv(DASHBOARD_PS_ENV, "1") or "1").strip().lower()
    return raw not in {"0", "off", "false", "no"}


def dashboard_ps_interval_sec(default: float = DEFAULT_PS_INTERVAL_SEC) -> float:
    raw = (os.getenv(DASHBOARD_PS_INTERVAL_ENV) or "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return max(0.5, value)


def parse_ps_payload(payload: dict[str, Any] | list[Any]) -> list[dict[str, Any]]:
    """Normalize ``/api/ps`` JSON into ``[{model, size_bytes, size_vram_bytes}, ...]``."""
    if isinstance(payload, list):
        models = payload
    else:
        models = payload.get("models") or []
    out: list[dict[str, Any]] = []
    for entry in models:
        if not isinstance(entry, dict):
            continue
        name = entry.get("model") or entry.get("name")
        if not isinstance(name, str) or not name:
            continue
        size = entry.get("size") or entry.get("size_vram") or 0
        size_vram = entry.get("size_vram") or 0
        try:
            size_i = int(size)
        except (TypeError, ValueError):
            size_i = 0
        try:
            vram_i = int(size_vram)
        except (TypeError, ValueError):
            vram_i = 0
        out.append(
            {
                "model": name,
                "size_bytes": size_i or vram_i,
                "size_vram_bytes": vram_i,
            }
        )
    return out


def list_resident_models(host: str, *, timeout_sec: float = DEFAULT_PS_TIMEOUT_SEC) -> list[dict[str, Any]]:
    base = host.rstrip("/")
    if not base.startswith("http"):
        base = f"http://{base}"
    url = f"{base}/api/ps"
    request = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(request, timeout=timeout_sec) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, (dict, list)):
        return []
    return parse_ps_payload(payload)


def _normalize_host(host: str) -> str:
    base = host.rstrip("/")
    if not base.startswith("http"):
        base = f"http://{base}"
    return base


def cached_resident_models(
    host: str,
    *,
    interval_sec: float | None = None,
    timeout_sec: float = DEFAULT_PS_TIMEOUT_SEC,
    force: bool = False,
) -> list[dict[str, Any]] | None:
    """Return resident models, refreshing at most once per ``interval_sec``.

    On probe failure, returns the last good list (possibly stale) or None.
    """
    key = _normalize_host(host)
    ttl = dashboard_ps_interval_sec() if interval_sec is None else max(0.5, float(interval_sec))
    now = time.monotonic()
    with _cache_lock:
        cached = _ps_cache.get(key)
        if not force and cached is not None and (now - cached[0]) < ttl:
            return list(cached[1])

    try:
        residents = list_resident_models(key, timeout_sec=timeout_sec)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        log.debug("ollama ps probe failed for %s: %s", key, exc)
        with _cache_lock:
            cached = _ps_cache.get(key)
            return list(cached[1]) if cached is not None else None

    with _cache_lock:
        _ps_cache[key] = (time.monotonic(), list(residents))
    return residents


def clear_ps_cache() -> None:
    with _cache_lock:
        _ps_cache.clear()


def _snapshot_from_residents(
    residents: list[dict[str, Any]],
    *,
    in_flight: dict[str, int],
    budget_bytes: int | None,
    ps_disabled: bool = False,
) -> dict[str, Any]:
    models = []
    used = 0
    seen: set[str] = set()
    for row in residents:
        name = row["model"]
        size = int(row.get("size_bytes") or 0)
        used += size
        seen.add(name)
        models.append(
            {
                "model": name,
                "size_bytes": size,
                "in_flight": int(in_flight.get(name, 0)),
            }
        )
    # Show in-flight models even if ps has not listed them yet (e.g. mid-load).
    for name, flight in sorted(in_flight.items()):
        if name in seen or flight <= 0:
            continue
        models.append({"model": name, "size_bytes": 0, "in_flight": int(flight)})
    return {
        "used_bytes": used,
        "budget_bytes": int(budget_bytes if budget_bytes is not None else used),
        "models": models,
        "ps_disabled": ps_disabled,
    }


def residency_snapshot_from_ps(
    host: str,
    *,
    in_flight: dict[str, int] | None = None,
    budget_bytes: int | None = None,
) -> dict[str, Any] | None:
    """Build a dashboard ``models_in_mem`` snapshot.

    ``/api/ps`` is polled at most every ``WORKER_DASHBOARD_OLLAMA_PS_INTERVAL_SEC``
    (default 5s). In-flight counts are applied every call from the router (no HTTP).
    """
    flight = in_flight or {}
    if not dashboard_ollama_ps_enabled():
        return _snapshot_from_residents(
            [],
            in_flight=flight,
            budget_bytes=budget_bytes,
            ps_disabled=True,
        )

    residents = cached_resident_models(host)
    if residents is None:
        # No successful probe yet — still show in-flight dots without sizes.
        if not flight:
            return None
        return _snapshot_from_residents(
            [],
            in_flight=flight,
            budget_bytes=budget_bytes,
            ps_disabled=False,
        )
    return _snapshot_from_residents(
        residents,
        in_flight=flight,
        budget_bytes=budget_bytes,
        ps_disabled=False,
    )
