from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass

log = logging.getLogger(__name__)

STUCK_WARN_AFTER_SEC = 120.0
STUCK_WARN_INTERVAL_SEC = 60.0


@dataclass(frozen=True)
class InflightCall:
    call_id: int
    job_id: str | None
    model: str
    role: str
    backend: str
    started_at: float


class InflightTracker:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._next_id = 1
        self._calls: dict[int, InflightCall] = {}
        self._last_warn_at = 0.0

    def start(
        self,
        *,
        job_id: str | None,
        model: str,
        role: str,
        backend: str,
    ) -> int:
        with self._lock:
            call_id = self._next_id
            self._next_id += 1
            self._calls[call_id] = InflightCall(
                call_id=call_id,
                job_id=job_id,
                model=model,
                role=role,
                backend=backend,
                started_at=time.monotonic(),
            )
            return call_id

    def finish(self, call_id: int) -> None:
        with self._lock:
            self._calls.pop(call_id, None)

    def snapshot(self) -> list[dict[str, object]]:
        now = time.monotonic()
        with self._lock:
            rows = list(self._calls.values())
        return [
            {
                "job_id": call.job_id,
                "model": call.model,
                "role": call.role,
                "backend": call.backend,
                "elapsed_sec": max(0, int(now - call.started_at)),
            }
            for call in rows
        ]

    def maybe_warn_stuck(
        self,
        *,
        after_sec: float = STUCK_WARN_AFTER_SEC,
        interval_sec: float = STUCK_WARN_INTERVAL_SEC,
    ) -> None:
        now = time.monotonic()
        if now - self._last_warn_at < interval_sec:
            return
        stuck = [
            row for row in self.snapshot() if int(row["elapsed_sec"]) >= after_sec
        ]
        if not stuck:
            return
        self._last_warn_at = now
        summary = ", ".join(
            f"{row['job_id'] or '-'} {row['model']} ({row['elapsed_sec']}s)"
            for row in stuck
        )
        log.warning(
            "Router Ollama call(s) still in flight: %s. "
            "If `ollama ps` shows Stopping..., restart Ollama; "
            "set OLLAMA_CHAT_TIMEOUT_SEC to fail fast.",
            summary,
        )
