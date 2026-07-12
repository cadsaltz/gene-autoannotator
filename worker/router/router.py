from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass

log = logging.getLogger(__name__)


class ModelNotFoundError(LookupError):
    def __init__(self, model: str, known: set[str]) -> None:
        self.model = model
        self.known = known
        super().__init__(f"Unknown model {model!r}; known models: {sorted(known)}")


@dataclass
class Backend:
    host: str
    models: set[str]
    parallel: int

    @property
    def gate_capacity(self) -> int:
        """Max concurrent Ollama HTTP requests to this server (``OLLAMA_NUM_PARALLEL``)."""
        return max(1, self.parallel)


class ModelRouter:
    """Routes models to backends with a single server-level gate per Ollama host."""

    def __init__(self, backends: list[Backend]) -> None:
        self._backends = list(backends)
        self._in_flight: dict[int, int] = {}
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)
        self._backends_by_model: dict[str, list[Backend]] = {}
        for backend in backends:
            for model in backend.models:
                self._backends_by_model.setdefault(model, []).append(backend)
        self._known_models = set(self._backends_by_model)

    def _in_flight_for(self, backend: Backend) -> int:
        return self._in_flight.get(id(backend), 0)

    def _has_capacity(self, backend: Backend) -> bool:
        return self._in_flight_for(backend) < backend.gate_capacity

    def acquire(
        self,
        model: str,
        *,
        timeout: float | None = None,
        job_id: str | None = None,
        role: str | None = None,
    ) -> Backend:
        if model not in self._known_models:
            raise ModelNotFoundError(model, self._known_models)

        candidates = self._backends_by_model[model]
        deadline = None if timeout is None else time.monotonic() + timeout
        wait_started = time.monotonic()

        with self._cond:
            while True:
                available = [backend for backend in candidates if self._has_capacity(backend)]
                if available:
                    backend = min(available, key=self._in_flight_for)
                    key = id(backend)
                    self._in_flight[key] = self._in_flight.get(key, 0) + 1
                    waited_ms = int((time.monotonic() - wait_started) * 1000)
                    if waited_ms >= 1000:
                        log.info(
                            "router acquired gate job=%s model=%s role=%s backend=%s wait=%dms",
                            job_id or "-",
                            model,
                            role or "-",
                            backend.host,
                            waited_ms,
                        )
                    return backend

                if timeout is not None:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError(
                            f"No capacity for model {model!r} within {timeout}s"
                        )
                    wait_for = min(30.0, remaining)
                else:
                    wait_for = 30.0

                if timeout is not None:
                    if not self._cond.wait(timeout=wait_for):
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise TimeoutError(
                                f"No capacity for model {model!r} within {timeout}s"
                            )
                else:
                    self._cond.wait(timeout=wait_for)

    def release(self, backend: Backend, model: str) -> None:
        del model  # server gate is model-agnostic; kept for call-site compatibility
        key = id(backend)
        with self._cond:
            count = self._in_flight.get(key)
            if count is None or count <= 0:
                raise ValueError(
                    f"backend {backend.host!r} has no in-flight requests to release"
                )
            if count == 1:
                del self._in_flight[key]
            else:
                self._in_flight[key] = count - 1
            self._cond.notify_all()
