from __future__ import annotations

import threading
import time
from dataclasses import dataclass


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


class ModelRouter:
    def __init__(self, backends: list[Backend]) -> None:
        self._backends = list(backends)
        self._in_flight: dict[tuple[int, str], int] = {}
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)
        self._backends_by_model: dict[str, list[Backend]] = {}
        for backend in backends:
            for model in backend.models:
                self._backends_by_model.setdefault(model, []).append(backend)
        self._known_models = set(self._backends_by_model)

    def _in_flight_for(self, backend: Backend, model: str) -> int:
        return self._in_flight.get((id(backend), model), 0)

    def acquire(self, model: str, *, timeout: float | None = None) -> Backend:
        if model not in self._known_models:
            raise ModelNotFoundError(model, self._known_models)

        candidates = self._backends_by_model[model]
        deadline = None if timeout is None else time.monotonic() + timeout

        with self._cond:
            while True:
                available = [
                    backend
                    for backend in candidates
                    if self._in_flight_for(backend, model) < backend.parallel
                ]
                if available:
                    backend = min(available, key=lambda b: self._in_flight_for(b, model))
                    key = (id(backend), model)
                    self._in_flight[key] = self._in_flight.get(key, 0) + 1
                    return backend

                if timeout is not None:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError(
                            f"No capacity for model {model!r} within {timeout}s"
                        )
                    if not self._cond.wait(timeout=remaining):
                        raise TimeoutError(
                            f"No capacity for model {model!r} within {timeout}s"
                        )
                else:
                    self._cond.wait()

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
            self._cond.notify_all()
