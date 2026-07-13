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


def ollama_chat_timeout_for_role(role: str) -> float | None:
    """Read timeout for one Ollama chat call (``None`` = unlimited).

    Unset ``OLLAMA_CHAT_TIMEOUT_SEC`` waits indefinitely — required for large
    performance models that may run many minutes per call. Set a positive value
    only when you want bench/debug fail-fast behavior.
    """
    del role
    return _optional_timeout_env("OLLAMA_CHAT_TIMEOUT_SEC", default=None)


def router_http_timeout() -> httpx.Timeout:
    """Router client timeout: short connect, unlimited read by default."""
    connect = _float_env("OLLAMA_ROUTER_CONNECT_TIMEOUT_SEC", CONNECT_TIMEOUT_SECONDS_DEFAULT)
    read = _optional_timeout_env("OLLAMA_ROUTER_READ_TIMEOUT_SEC", default=None)
    if read is None:
        return httpx.Timeout(None, connect=connect)
    return httpx.Timeout(read, connect=connect)


def ollama_chat_timeout() -> float | None:
    """Global Ollama chat read timeout if explicitly configured."""
    return _optional_timeout_env("OLLAMA_CHAT_TIMEOUT_SEC", default=None)
