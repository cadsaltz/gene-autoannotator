from __future__ import annotations

import os

import httpx

CONNECT_TIMEOUT_SECONDS_DEFAULT = 30.0


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


def router_http_timeout() -> httpx.Timeout:
    """Router client timeout: short connect, unbounded read by default."""
    connect = _float_env("OLLAMA_ROUTER_CONNECT_TIMEOUT_SEC", CONNECT_TIMEOUT_SECONDS_DEFAULT)
    read = _optional_timeout_env("OLLAMA_ROUTER_READ_TIMEOUT_SEC", default=None)
    return httpx.Timeout(read, connect=connect)


def ollama_chat_timeout() -> float | None:
    """Ollama Python client timeout from the router sidecar (None = unlimited)."""
    return _optional_timeout_env("OLLAMA_CHAT_TIMEOUT_SEC", default=None)


def router_read_timeout_for_load(*, slots: int, lanes: int) -> float | None:
    """Optional finite read timeout when slots oversubscribe lanes.

    Returns None when OLLAMA_ROUTER_READ_TIMEOUT_SEC is unset (unlimited).
    When set to a positive base value, scales by ceil(slots/lanes).
    """
    base = _optional_timeout_env("OLLAMA_ROUTER_READ_TIMEOUT_SEC", default=None)
    if base is None:
        return None
    lanes = max(1, int(lanes))
    slots = max(1, int(slots))
    queue_factor = max(1, (slots + lanes - 1) // lanes)
    return base * queue_factor + 30.0


def ensure_router_read_timeout_for_load(*, slots: int, lanes: int) -> float | None:
    """Apply scaled finite read timeout when explicitly configured."""
    if os.getenv("OLLAMA_ROUTER_READ_TIMEOUT_SEC") is None:
        return None
    timeout = router_read_timeout_for_load(slots=slots, lanes=lanes)
    if timeout is None:
        os.environ.pop("OLLAMA_ROUTER_READ_TIMEOUT_SEC", None)
    else:
        os.environ["OLLAMA_ROUTER_READ_TIMEOUT_SEC"] = str(int(timeout))
    return timeout
