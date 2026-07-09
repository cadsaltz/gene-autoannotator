from __future__ import annotations

import httpx


class RouterClient:
    def __init__(self, base_url: str) -> None:
        self._http = httpx.Client(base_url=base_url, timeout=600.0)

    def chat(
        self,
        *,
        model: str,
        messages: list[dict],
        format=None,
        role: str = "inference",
        job_id: str | None = None,
    ) -> dict:
        payload: dict = {
            "model": model,
            "messages": messages,
            "role": role,
            "job_id": job_id,
        }
        if format is not None:
            payload["format"] = format
        response = self._http.post("/v1/chat", json=payload)
        response.raise_for_status()
        return response.json()
