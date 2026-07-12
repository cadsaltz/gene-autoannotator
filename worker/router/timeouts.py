from __future__ import annotations

import os

import httpx

CONNECT_TIMEOUT_SECONDS_DEFAULT = 30.0

ROLE_CHAT_TIMEOUT_DEFAULTS: dict[str, float] = {
    "section_summary": 120.0,
    "section_consensus": 180.0,
    "gene_aggregation": 600.0,
    "inference": 300.0,
}

DEFAULT_CHAT_TIMEOUT_SEC = 300.0
ROUTER_READ_BUFFER_SEC = 30.0


def _float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _optional_timeout_env(name: str, *, default: float | None = None) -> float | None:
    """Parse a timeout env var.

    Unset uses `default`. ``0``, ``none``, ``off``, and negative values mean no
    timeout (wait indefinitely). Positive values set a finite timeout in seconds.
    """
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return default
    normalized = raw.strip().lower()
    if normalized in {"0", "none", "off", "false", "no", "unlimited", "inf", "infinite"}:
        return None
    try:
        value = float(raw)
    except ValueError:
        return default
    if value <= 0:
        return None
    return value


def ollama_chat_timeout_for_role(role: str) -> float:
    """Finite timeout for one Ollama chat call.

    ``OLLAMA_CHAT_TIMEOUT_SEC`` overrides all roles when set to a positive value.
    When unset, uses per-role defaults. When set to unlimited (``0``), falls back
    to per-role defaults anyway so bench runs never hang forever on one call.
    """
    global_cap = _optional_timeout_env("OLLAMA_CHAT_TIMEOUT_SEC", default=None)
    role_default = ROLE_CHAT_TIMEOUT_DEFAULTS.get(role, DEFAULT_CHAT_TIMEOUT_SEC)
    if global_cap is None:
        return role_default
    return global_cap


def router_http_timeout() -> httpx.Timeout:
    """Router client timeout: short connect, read capped for hung router threads."""
    connect = _float_env("OLLAMA_ROUTER_CONNECT_TIMEOUT_SEC", CONNECT_TIMEOUT_SECONDS_DEFAULT)
    read = _optional_timeout_env("OLLAMA_ROUTER_READ_TIMEOUT_SEC", default=None)
    if read is None:
        max_role = max(ROLE_CHAT_TIMEOUT_DEFAULTS.values(), default=DEFAULT_CHAT_TIMEOUT_SEC)
        global_cap = _optional_timeout_env("OLLAMA_CHAT_TIMEOUT_SEC", default=None)
        if global_cap is not None:
            max_role = global_cap
        read = max_role + ROUTER_READ_BUFFER_SEC
    return httpx.Timeout(read, connect=connect)


def ollama_chat_timeout() -> float | None:
    """Legacy helper: global Ollama timeout if explicitly configured."""
    return _optional_timeout_env("OLLAMA_CHAT_TIMEOUT_SEC", default=None)
