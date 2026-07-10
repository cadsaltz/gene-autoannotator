from __future__ import annotations

import os

import httpx

_ROUTER_METADATA_KEYS = frozenset({'backend', 'queue_wait_ms'})


def _router_http_timeout() -> float:
    raw = os.getenv("OLLAMA_ROUTER_HTTP_TIMEOUT_SEC", "180")
    try:
        return float(raw)
    except ValueError:
        return 180.0


class RouterClient:
    def __init__(self, base_url: str) -> None:
        self._http = httpx.Client(base_url=base_url, timeout=_router_http_timeout())

    def chat(
        self,
        *,
        model: str,
        messages: list[dict],
        format=None,
        role: str = "inference",
        job_id: str | None = None,
        keep_alive: int | str | None = None,
    ) -> dict:
        payload: dict = {
            "model": model,
            "messages": messages,
            "role": role,
            "job_id": job_id,
        }
        if format is not None:
            payload["format"] = format
        if keep_alive is not None:
            payload["keep_alive"] = keep_alive
        response = self._http.post("/v1/chat", json=payload)
        response.raise_for_status()
        payload = response.json()
        return {k: v for k, v in payload.items() if k not in _ROUTER_METADATA_KEYS}
