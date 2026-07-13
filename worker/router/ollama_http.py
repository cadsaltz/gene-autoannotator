from __future__ import annotations

import httpx

CONNECT_TIMEOUT_SECONDS = 30.0


def _httpx_timeout(read_sec: float | None) -> httpx.Timeout:
    if read_sec is None:
        return httpx.Timeout(None, connect=CONNECT_TIMEOUT_SECONDS)
    return httpx.Timeout(read_sec, connect=CONNECT_TIMEOUT_SECONDS)


def chat(
    host: str,
    *,
    model: str,
    messages: list[dict],
    format=None,
    keep_alive: int | str | None = None,
    timeout_sec: float | None = None,
) -> dict:
    """Call Ollama ``/api/chat`` (``timeout_sec=None`` waits indefinitely)."""
    url = f"{host.rstrip('/')}/api/chat"
    body: dict = {
        "model": model,
        "messages": messages,
        "stream": False,
    }
    if format is not None:
        body["format"] = format
    if keep_alive is not None:
        body["keep_alive"] = keep_alive

    with httpx.Client(timeout=_httpx_timeout(timeout_sec)) as client:
        response = client.post(url, json=body)
        response.raise_for_status()
        payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError(f"Ollama returned non-object JSON: {type(payload).__name__}")
    return payload
