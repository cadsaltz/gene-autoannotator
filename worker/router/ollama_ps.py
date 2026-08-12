"""Ollama ``/api/ps`` helpers for dashboard residency (optional probe)."""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from typing import Any

log = logging.getLogger(__name__)

DASHBOARD_PS_ENV = "WORKER_DASHBOARD_OLLAMA_PS"


def dashboard_ollama_ps_enabled() -> bool:
    raw = (os.getenv(DASHBOARD_PS_ENV, "1") or "1").strip().lower()
    return raw not in {"0", "off", "false", "no"}


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


def list_resident_models(host: str, *, timeout_sec: float = 2.0) -> list[dict[str, Any]]:
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


def residency_snapshot_from_ps(
    host: str,
    *,
    in_flight: dict[str, int] | None = None,
    budget_bytes: int | None = None,
) -> dict[str, Any] | None:
    """Build a dashboard ``models_in_mem`` snapshot from live ``/api/ps``.

    Returns None when the probe is disabled or the request fails.
    """
    if not dashboard_ollama_ps_enabled():
        return {
            "used_bytes": 0,
            "budget_bytes": int(budget_bytes or 0),
            "models": [],
            "ps_disabled": True,
        }
    try:
        residents = list_resident_models(host)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        log.debug("ollama ps probe failed for %s: %s", host, exc)
        return None
    flight = in_flight or {}
    models = []
    used = 0
    for row in residents:
        name = row["model"]
        size = int(row.get("size_bytes") or 0)
        used += size
        models.append(
            {
                "model": name,
                "size_bytes": size,
                "in_flight": int(flight.get(name, 0)),
            }
        )
    return {
        "used_bytes": used,
        "budget_bytes": int(budget_bytes if budget_bytes is not None else used),
        "models": models,
        "ps_disabled": False,
    }
