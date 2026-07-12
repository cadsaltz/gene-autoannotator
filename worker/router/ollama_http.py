from __future__ import annotations

import httpx

CONNECT_TIMEOUT_SECONDS = 30.0


def chat(
    host: str,
    *,
    model: str,
    messages: list[dict],
    format=None,
    keep_alive: int | str | None = None,
    timeout_sec: float,
) -> dict:
    """Call Ollama ``/api/chat`` with a hard read timeout.

    Uses httpx instead of ``ollama.Client`` so hung inference fails fast and the
    connection is closed, releasing the server gate for the next request.
    """
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

    timeout = httpx.Timeout(timeout_sec, connect=CONNECT_TIMEOUT_SECONDS)
    with httpx.Client(timeout=timeout) as client:
        response = client.post(url, json=body)
        response.raise_for_status()
        payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError(f"Ollama returned non-object JSON: {type(payload).__name__}")
    return payload
