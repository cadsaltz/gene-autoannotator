"""Thread-safe model residency cache for one Ollama backend."""

from dataclasses import dataclass
import threading
import time
from typing import Any, Callable


@dataclass
class _Entry:
    size: int
    refcount: int
    last_used: float
    loading: bool = False


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
        self._last_snapshot: dict[str, Any] = {
            "used_bytes": 0,
            "budget_bytes": budget_bytes,
            "models": [],
        }

    def ensure(self, model: str) -> None:
        """Block until ``model`` is resident and refcount incremented."""
        need = self._model_sizes[model]
        if need > self._budget_bytes:
            raise ValueError(
                f"Model {model!r} requires {need} bytes, exceeding cache "
                f"budget of {self._budget_bytes} bytes"
            )

        deadline = time.monotonic() + self._wait_timeout_sec
        while True:
            action: tuple[str, str] | tuple[str] | None = None
            with self._condition:
                entry = self._entries.get(model)
                if entry is not None:
                    if entry.loading:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0 or not self._condition.wait(timeout=remaining):
                            raise TimeoutError(
                                f"Timed out waiting for model {model!r} to finish loading"
                            )
                        continue
                    entry.refcount += 1
                    entry.last_used = time.monotonic()
                    self._publish_snapshot_unlocked()
                    return

                if self._used_bytes_unlocked() + need > self._budget_bytes:
                    idle = [
                        (name, candidate)
                        for name, candidate in self._entries.items()
                        if candidate.refcount == 0 and not candidate.loading
                    ]
                    if idle:
                        victim, _ = min(idle, key=lambda item: item[1].last_used)
                        del self._entries[victim]
                        self._publish_snapshot_unlocked()
                        action = ("unload", victim)
                    else:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0 or not self._condition.wait(timeout=remaining):
                            busy = sorted(
                                name
                                for name, candidate in self._entries.items()
                                if candidate.refcount > 0 or candidate.loading
                            )
                            raise TimeoutError(
                                f"Timed out waiting to load model {model!r}; "
                                f"busy models blocking cache space: {busy}"
                            )
                else:
                    self._entries[model] = _Entry(
                        size=need,
                        refcount=1,
                        last_used=time.monotonic(),
                        loading=True,
                    )
                    self._publish_snapshot_unlocked()
                    action = ("load",)

            if action is None:
                continue
            if action[0] == "unload":
                self._unload_fn(self._host, action[1])
                continue

            try:
                self._load_fn(self._host, model)
            except Exception:
                with self._condition:
                    self._entries.pop(model, None)
                    self._publish_snapshot_unlocked()
                    self._condition.notify_all()
                raise

            with self._condition:
                loaded = self._entries.get(model)
                if loaded is not None:
                    loaded.loading = False
                    loaded.last_used = time.monotonic()
                    self._publish_snapshot_unlocked()
                self._condition.notify_all()
            return

    def release(self, model: str) -> None:
        """Decrement refcount after a chat finishes (model stays resident)."""
        with self._condition:
            entry = self._entries[model]
            entry.refcount = max(0, entry.refcount - 1)
            self._publish_snapshot_unlocked()
            self._condition.notify_all()

    @property
    def resident(self) -> frozenset[str]:
        with self._condition:
            return frozenset(
                name for name, entry in self._entries.items() if not entry.loading
            )

    def residency_snapshot(self) -> dict:
        """Return resident models, sizes, and budget (never blocks on Ollama I/O)."""
        acquired = self._condition.acquire(blocking=False)
        if not acquired:
            return self._copy_snapshot(self._last_snapshot)
        try:
            self._publish_snapshot_unlocked()
            return self._copy_snapshot(self._last_snapshot)
        finally:
            self._condition.release()

    def used_bytes(self) -> int:
        with self._condition:
            return self._used_bytes_unlocked()

    def _used_bytes_unlocked(self) -> int:
        return sum(entry.size for entry in self._entries.values())

    def _publish_snapshot_unlocked(self) -> None:
        self._last_snapshot = {
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

    @staticmethod
    def _copy_snapshot(snap: dict[str, Any]) -> dict[str, Any]:
        return {
            "used_bytes": snap.get("used_bytes", 0),
            "budget_bytes": snap.get("budget_bytes", 0),
            "models": [dict(row) for row in snap.get("models", [])],
        }
