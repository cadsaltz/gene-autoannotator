from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass

log = logging.getLogger(__name__)

LANE_WAIT_LOG_INTERVAL_SEC = 30.0


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
    max_in_flight: int | None = None

    @property
    def max_in_flight_total(self) -> int:
        """Max concurrent HTTP requests to this Ollama server (all models combined).

        Defaults to ``parallel``, matching ``OLLAMA_NUM_PARALLEL``. Per-model lanes
        still apply, but the backend total prevents sending more concurrent requests
        than Ollama can process (avoids wedged/hung inference).
        """
        if self.max_in_flight is not None:
            return max(1, self.max_in_flight)
        return max(1, self.parallel)


class ModelRouter:
    def __init__(self, backends: list[Backend]) -> None:
        self._backends = list(backends)
        self._in_flight: dict[tuple[int, str], int] = {}
        self._backend_in_flight: dict[int, int] = {}
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)
        self._backends_by_model: dict[str, list[Backend]] = {}
        for backend in backends:
            for model in backend.models:
                self._backends_by_model.setdefault(model, []).append(backend)
        self._known_models = set(self._backends_by_model)

    def _in_flight_for(self, backend: Backend, model: str) -> int:
        return self._in_flight.get((id(backend), model), 0)

    def _backend_total_in_flight(self, backend: Backend) -> int:
        return self._backend_in_flight.get(id(backend), 0)

    def _backend_has_capacity(self, backend: Backend, model: str) -> bool:
        return (
            self._in_flight_for(backend, model) < backend.parallel
            and self._backend_total_in_flight(backend) < backend.max_in_flight_total
        )

    def acquire(
        self,
        model: str,
        *,
        timeout: float | None = None,
        job_id: str | None = None,
        role: str | None = None,
        log_waits: bool = False,
    ) -> Backend:
        if model not in self._known_models:
            raise ModelNotFoundError(model, self._known_models)

        candidates = self._backends_by_model[model]
        deadline = None if timeout is None else time.monotonic() + timeout
        wait_started = time.monotonic()
        last_wait_log = wait_started

        with self._cond:
            while True:
                available = [
                    backend
                    for backend in candidates
                    if self._backend_has_capacity(backend, model)
                ]
                if available:
                    backend = min(
                        available,
                        key=lambda b: (
                            self._backend_total_in_flight(b),
                            self._in_flight_for(b, model),
                        ),
                    )
                    key = (id(backend), model)
                    self._in_flight[key] = self._in_flight.get(key, 0) + 1
                    backend_key = id(backend)
                    self._backend_in_flight[backend_key] = (
                        self._backend_in_flight.get(backend_key, 0) + 1
                    )
                    waited_ms = int((time.monotonic() - wait_started) * 1000)
                    if log_waits and waited_ms >= int(LANE_WAIT_LOG_INTERVAL_SEC * 1000):
                        log.info(
                            "router acquired lane job=%s model=%s role=%s backend=%s wait=%dms",
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
                    wait_for = min(LANE_WAIT_LOG_INTERVAL_SEC, remaining)
                else:
                    wait_for = LANE_WAIT_LOG_INTERVAL_SEC

                if log_waits:
                    elapsed = time.monotonic() - wait_started
                    if (
                        elapsed >= LANE_WAIT_LOG_INTERVAL_SEC
                        and time.monotonic() - last_wait_log >= LANE_WAIT_LOG_INTERVAL_SEC
                    ):
                        log.warning(
                            "router waiting for lane job=%s model=%s role=%s elapsed=%ds "
                            "(model lane or Ollama server at capacity; check `ollama ps`)",
                            job_id or "-",
                            model,
                            role or "-",
                            int(elapsed),
                        )
                        last_wait_log = time.monotonic()

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
        key = (id(backend), model)
        with self._cond:
            count = self._in_flight.get(key)
            if count is None:
                raise ValueError(
                    f"backend {backend.host!r} has no in-flight requests for model {model!r}"
                )
            if count <= 0:
                raise ValueError(
                    f"backend {backend.host!r} has no in-flight requests for model {model!r}"
                )
            if count == 1:
                del self._in_flight[key]
            else:
                self._in_flight[key] = count - 1
            backend_key = id(backend)
            backend_count = self._backend_in_flight.get(backend_key, 0)
            if backend_count <= 1:
                self._backend_in_flight.pop(backend_key, None)
            else:
                self._backend_in_flight[backend_key] = backend_count - 1
            self._cond.notify_all()
