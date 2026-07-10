from __future__ import annotations

import os

import httpx


def _float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def router_http_timeout() -> httpx.Timeout:
    """Short connect timeout; long read timeout for slow LLM inference."""
    connect = _float_env("OLLAMA_ROUTER_CONNECT_TIMEOUT_SEC", 30.0)
    read = _float_env("OLLAMA_ROUTER_READ_TIMEOUT_SEC", 600.0)
    return httpx.Timeout(read, connect=connect)


def ollama_chat_timeout() -> float:
    """Seconds for Ollama Python client calls from the router sidecar."""
    return _float_env("OLLAMA_CHAT_TIMEOUT_SEC", 600.0)
