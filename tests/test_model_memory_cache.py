import threading

from worker.router.model_cache import ModelMemoryCache


class FakeOllama:
    def __init__(self):
        self.loaded: set[str] = set()
        self.unloads: list[str] = []
        self.loads: list[str] = []

    def unload(self, host, model):
        self.unloads.append(model)
        self.loaded.discard(model)

    def load(self, host, model):
        self.loads.append(model)
        self.loaded.add(model)


def _cache(fake: FakeOllama, budget: int, sizes: dict[str, int]) -> ModelMemoryCache:
    return ModelMemoryCache(
        host="http://127.0.0.1:11434",
        budget_bytes=budget,
        model_sizes=sizes,
        unload_fn=fake.unload,
        load_fn=fake.load,
        wait_timeout_sec=2.0,
    )


def test_ensure_hit_increments_refcount_without_reload():
    fake = FakeOllama()
    sizes = {"a": 5, "b": 5}
    cache = _cache(fake, budget=10, sizes=sizes)
    cache.ensure("a")
    cache.release("a")
    fake.loads.clear()
    cache.ensure("a")
    assert fake.loads == []
    assert "a" in cache.resident
    cache.release("a")


def test_ensure_evicts_lru_idle_models_until_space_fits():
    fake = FakeOllama()
    sizes = {"a": 4, "b": 4, "c": 7}
    cache = _cache(fake, budget=10, sizes=sizes)
    cache.ensure("a"); cache.release("a")
    cache.ensure("b"); cache.release("b")
    # resident a,b used=8; need c=7, so one 4-byte eviction is insufficient
    cache.ensure("c")
    assert cache.resident == frozenset({"c"})
    assert fake.unloads == ["a", "b"]
    cache.release("c")


def test_ensure_waits_when_only_busy_models_block_space():
    fake = FakeOllama()
    sizes = {"a": 8, "b": 8}
    cache = _cache(fake, budget=10, sizes=sizes)
    cache.ensure("a")  # busy, refcount=1

    done = {"ok": False}
    entered_wait = threading.Event()
    original_wait = cache._condition.wait

    def observed_wait(timeout=None):
        entered_wait.set()
        return original_wait(timeout)

    cache._condition.wait = observed_wait

    def other():
        cache.ensure("b")
        done["ok"] = True
        cache.release("b")

    t = threading.Thread(target=other)
    t.start()
    assert entered_wait.wait(timeout=1.0)
    assert done["ok"] is False  # blocked: cannot evict busy a
    cache.release("a")
    t.join(timeout=2.0)
    assert not t.is_alive()
    assert done["ok"] is True


def test_residency_snapshot_does_not_block_during_slow_load():
    """Dashboard must not freeze while Ollama load I/O runs."""
    import time

    release_load = threading.Event()
    load_started = threading.Event()

    def slow_load(host, model):
        load_started.set()
        assert release_load.wait(timeout=5.0)

    cache = ModelMemoryCache(
        host="http://127.0.0.1:11434",
        budget_bytes=10,
        model_sizes={"a": 5},
        unload_fn=lambda host, model: None,
        load_fn=slow_load,
        wait_timeout_sec=5.0,
    )

    loader = threading.Thread(target=lambda: cache.ensure("a"))
    loader.start()
    assert load_started.wait(timeout=1.0)

    t0 = time.monotonic()
    snap = cache.residency_snapshot()
    elapsed = time.monotonic() - t0
    assert elapsed < 0.25, f"snapshot blocked for {elapsed:.2f}s during load"
    assert isinstance(snap, dict)
    assert "models" in snap

    release_load.set()
    loader.join(timeout=2.0)
    assert not loader.is_alive()
    cache.release("a")