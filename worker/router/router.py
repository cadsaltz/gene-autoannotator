from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field


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
    in_flight: int = field(default=0, init=False, repr=False)


class ModelRouter:
    def __init__(self, backends: list[Backend]) -> None:
        self._backends = list(backends)
        self._in_flight = {id(backend): 0 for backend in backends}
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)
        self._backends_by_model: dict[str, list[Backend]] = {}
        for backend in backends:
            for model in backend.models:
                self._backends_by_model.setdefault(model, []).append(backend)
        self._known_models = set(self._backends_by_model)

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
                    if self._in_flight[id(backend)] < backend.parallel
                ]
                if available:
                    backend = min(available, key=lambda b: self._in_flight[id(b)])
                    self._in_flight[id(backend)] += 1
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

    def release(self, backend: Backend) -> None:
        key = id(backend)
        with self._cond:
            count = self._in_flight.get(key)
            if count is None:
                raise ValueError("backend is not managed by this router")
            if count <= 0:
                raise ValueError("backend has no in-flight requests")
            self._in_flight[key] -= 1
            self._cond.notify_all()
