"""Thread-safe model residency cache for one Ollama backend."""

from dataclasses import dataclass
import threading
import time
from typing import Callable


@dataclass
class _Entry:
    size: int
    refcount: int
    last_used: float


class ModelMemoryCache:
    def __init__(
        self,
        *,
        host: str,
        budget_bytes: int,
        model_sizes: dict[str, int],
        unload_fn: Callable[[str, str], None],
        load_fn: Callable[[str, str], None],
        wait_timeout_sec: float = 600.0,
    ) -> None:
        self._host = host
        self._budget_bytes = budget_bytes
        self._model_sizes = model_sizes
        self._unload_fn = unload_fn
        self._load_fn = load_fn
        self._wait_timeout_sec = wait_timeout_sec
        self._entries: dict[str, _Entry] = {}
        self._condition = threading.Condition(threading.Lock())

    def ensure(self, model: str) -> None:
        """Block until ``model`` is resident and refcount incremented."""
        need = self._model_sizes[model]
        if need > self._budget_bytes:
            raise ValueError(
                f"Model {model!r} requires {need} bytes, exceeding cache "
                f"budget of {self._budget_bytes} bytes"
            )

        with self._condition:
            entry = self._entries.get(model)
            if entry is not None:
                entry.refcount += 1
                entry.last_used = time.monotonic()
                return

            deadline = time.monotonic() + self._wait_timeout_sec
            while self._used_bytes_unlocked() + need > self._budget_bytes:
                idle = [
                    (name, candidate)
                    for name, candidate in self._entries.items()
                    if candidate.refcount == 0
                ]
                if idle:
                    victim, _ = min(idle, key=lambda item: item[1].last_used)
                    self._unload_fn(self._host, victim)
                    del self._entries[victim]
                    continue

                remaining = deadline - time.monotonic()
                if remaining <= 0 or not self._condition.wait(timeout=remaining):
                    busy = sorted(
                        name
                        for name, candidate in self._entries.items()
                        if candidate.refcount > 0
                    )
                    raise TimeoutError(
                        f"Timed out waiting to load model {model!r}; "
                        f"busy models blocking cache space: {busy}"
                    )

            self._load_fn(self._host, model)
            self._entries[model] = _Entry(
                size=need,
                refcount=1,
                last_used=time.monotonic(),
            )
            self._condition.notify_all()

    def release(self, model: str) -> None:
        """Decrement refcount after a chat finishes (model stays resident)."""
        with self._condition:
            entry = self._entries[model]
            entry.refcount = max(0, entry.refcount - 1)
            self._condition.notify_all()

    @property
    def resident(self) -> frozenset[str]:
        with self._condition:
            return frozenset(self._entries)

    def residency_snapshot(self) -> dict:
        """Return resident models, sizes, and budget (no Ollama I/O)."""
        with self._condition:
            return {
                "used_bytes": self._used_bytes_unlocked(),
                "budget_bytes": self._budget_bytes,
                "models": [
                    {
                        "model": name,
                        "size_bytes": entry.size,
                        "in_flight": entry.refcount,
                    }
                    for name, entry in sorted(self._entries.items())
                ],
            }

    def used_bytes(self) -> int:
        with self._condition:
            return self._used_bytes_unlocked()

    def _used_bytes_unlocked(self) -> int:
        return sum(entry.size for entry in self._entries.values())
