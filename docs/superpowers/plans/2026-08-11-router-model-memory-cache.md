# Router Model Memory Cache Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Spec:** `docs/superpowers/specs/2026-08-11-router-model-memory-cache-design.md`

**Goal:** Make the worker router treat VRAM+RAM as an LRU model weight cache (evict idle models only when space is needed; skip pre-warm unless the full stack fits) so overflow machines stop crashing during warm-all.

**Architecture:** Add a per-Ollama-backend `ModelMemoryCache` that tracks residency, refcounts, and LRU order; before each chat it ensures the model is loaded (evicting idle LRU victims via Ollama `keep_alive=0` unload API, or waiting if all residents are busy). Align fleet budget math to 10% headroom on VRAM and RAM, capped by `WORKER_MODEL_MEMORY_BUDGET_GB`. Bench/serve pre-warm only when `sum(model sizes) <= cache_budget`.

**Tech Stack:** Python 3, `threading`, existing `httpx` Ollama HTTP helpers, pytest, worker fleet sizing/probe.

## Global Constraints

- Cache budget: `0.9 * sum(VRAM) + 0.9 * system_RAM`, then `min(..., WORKER_MODEL_MEMORY_BUDGET_GB)` when set (`-1`/omit = no user cap).
- Evict only idle (`refcount == 0`) residents, LRU first; evict as many as needed for space.
- If all residents are busy and space is insufficient → wait until one is idle (with timeout), then retry.
- Pre-warm only if full required stack fits in budget; otherwise skip.
- Unload via Ollama API: `POST /api/generate` with `{"model": name, "keep_alive": 0}` (empty prompt).
- Load/pin with `keep_alive=-1` so Ollama does not timer-evict under the cache.
- Do not default `OLLAMA_MAX_LOADED_MODELS=1` for overflow/swap; set at least `len(required_models)`.
- Single-backend correctness first; one cache instance per Ollama host.
- TDD; no `git add .` / `git add -A` — named paths only.

## File map

| Path | Action | Responsibility |
|------|--------|----------------|
| `worker/fleet/sizing.py` | Modify | 10% VRAM/RAM headroom; shared `cache_budget_bytes` |
| `worker/router/ollama_http.py` | Modify | Add `generate` / `unload_model` helpers |
| `worker/router/model_cache.py` | Create | `ModelMemoryCache` policy + lock/wait |
| `worker/router/server.py` | Modify | Ensure cache before chat; forever keep_alive when cache on |
| `worker/fleet/setup.py` | Modify | `effective_max_loaded_models` no longer forces 1 |
| `worker/bench.py` | Modify | Conditional pre-warm from budget |
| `worker/serve.py` | Modify | Same pre-warm gate when warm-all enabled |
| `tests/test_fleet_sizing_cache_budget.py` | Create | Budget math tests |
| `tests/test_model_memory_cache.py` | Create | Cache unit tests (fake unload/load) |
| `tests/test_bench_prewarm_gate.py` | Create | Pre-warm skip/fit helpers |

---

### Task 1: Cache budget helpers (10% headroom + user cap)

**Files:**
- Modify: `worker/fleet/sizing.py`
- Create: `tests/test_fleet_sizing_cache_budget.py`

**Interfaces:**
- Consumes: `SystemSpec` from `worker.probe`
- Produces:
  - `VRAM_HEADROOM_RATIO = 0.10`
  - `RAM_HEADROOM_RATIO = 0.10` (replace `RAM_MODEL_RATIO = 0.50` usage for model cache budget)
  - `def cache_budget_bytes(spec: SystemSpec, *, user_budget_gb: float | None = None, num_servers: int = 1) -> int`
  - `vram_budget_for_fleet` / `ram_model_budget_bytes` / `total_model_budget_bytes` / `effective_model_budget_bytes` must use the new ratios so fleet + cache agree

- [ ] **Step 1: Write the failing test**

Create `tests/test_fleet_sizing_cache_budget.py`:

```python
from worker.fleet import sizing
from worker.probe import SystemSpec


def _spec(*, vram_gb=8.0, ram_gb=32.0) -> SystemSpec:
    return SystemSpec(
        gpu_count=1,
        vram_bytes=(int(vram_gb * 1024**3),),
        system_ram_bytes=int(ram_gb * 1024**3),
        cpu_physical=8,
        cpu_logical=16,
    )


def test_cache_budget_applies_10_percent_headroom_on_vram_and_ram():
    spec = _spec(vram_gb=10.0, ram_gb=20.0)
    # 0.9*10 + 0.9*20 = 27 GB
    expected = int(0.9 * 10 * 1024**3) + int(0.9 * 20 * 1024**3)
    assert sizing.cache_budget_bytes(spec) == expected


def test_cache_budget_respects_user_cap_gb():
    spec = _spec(vram_gb=10.0, ram_gb=20.0)
    capped = sizing.cache_budget_bytes(spec, user_budget_gb=12.0)
    assert capped == int(12.0 * 1024**3)


def test_cache_budget_ignores_unset_user_cap():
    spec = _spec(vram_gb=10.0, ram_gb=20.0)
    assert sizing.cache_budget_bytes(spec, user_budget_gb=None) == sizing.cache_budget_bytes(spec)
    assert sizing.cache_budget_bytes(spec, user_budget_gb=-1) == sizing.cache_budget_bytes(spec)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_fleet_sizing_cache_budget.py -v`  
Expected: FAIL (`cache_budget_bytes` missing and/or ratios still 0.15 / 0.50)

- [ ] **Step 3: Implement budget helpers**

In `worker/fleet/sizing.py`:

1. Set `VRAM_HEADROOM_RATIO = 0.10`.
2. Replace `RAM_MODEL_RATIO = 0.50` with `RAM_HEADROOM_RATIO = 0.10`.
3. Change `ram_model_budget_bytes` to `int(spec.system_ram_bytes * (1 - RAM_HEADROOM_RATIO))`.
4. Add:

```python
def cache_budget_bytes(
    spec: SystemSpec,
    *,
    user_budget_gb: float | None = None,
    num_servers: int = 1,
) -> int:
    """Model-weight cache budget: 90% VRAM + 90% RAM, optional user GB cap."""
    return effective_model_budget_bytes(
        spec, user_budget_gb=user_budget_gb, num_servers=num_servers
    )
```

Ensure `effective_model_budget_bytes` / `machine_model_cap_bytes` already call `total_model_budget_bytes` so they pick up the new ratios. Update any tests that hard-code the old 15%/50% expectations (`tests/test_fleet_sizing.py`) in the same commit if they fail.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_fleet_sizing_cache_budget.py tests/test_fleet_sizing.py -q`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add worker/fleet/sizing.py tests/test_fleet_sizing_cache_budget.py tests/test_fleet_sizing.py
git commit -m "feat(fleet): 10% VRAM/RAM headroom for model cache budget"
```

---

### Task 2: Ollama unload HTTP helper

**Files:**
- Modify: `worker/router/ollama_http.py`
- Create: `tests/test_ollama_http_unload.py`

**Interfaces:**
- Consumes: `httpx` (existing)
- Produces:
  - `def generate(host: str, *, model: str, prompt: str = "", keep_alive: int | str | None = None, timeout_sec: float | None = 60.0) -> dict`
  - `def unload_model(host: str, model: str, *, timeout_sec: float | None = 60.0) -> dict` → calls `generate(..., prompt="", keep_alive=0)`

- [ ] **Step 1: Write the failing test**

```python
from worker.router import ollama_http


def test_unload_model_posts_keep_alive_zero(monkeypatch):
    calls = []

    def fake_generate(host, *, model, prompt="", keep_alive=None, timeout_sec=None):
        calls.append(
            {
                "host": host,
                "model": model,
                "prompt": prompt,
                "keep_alive": keep_alive,
                "timeout_sec": timeout_sec,
            }
        )
        return {"done": True, "done_reason": "unload"}

    monkeypatch.setattr(ollama_http, "generate", fake_generate)
    out = ollama_http.unload_model("http://127.0.0.1:11434", "gemma3:12b")
    assert out["done_reason"] == "unload"
    assert calls == [
        {
            "host": "http://127.0.0.1:11434",
            "model": "gemma3:12b",
            "prompt": "",
            "keep_alive": 0,
            "timeout_sec": 60.0,
        }
    ]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_ollama_http_unload.py -v`  
Expected: FAIL (`generate` / `unload_model` missing)

- [ ] **Step 3: Implement**

Add to `worker/router/ollama_http.py` (mirror `chat`):

```python
def generate(
    host: str,
    *,
    model: str,
    prompt: str = "",
    keep_alive: int | str | None = None,
    timeout_sec: float | None = None,
) -> dict:
    url = f"{host.rstrip('/')}/api/generate"
    body: dict = {"model": model, "prompt": prompt, "stream": False}
    if keep_alive is not None:
        body["keep_alive"] = keep_alive
    with httpx.Client(timeout=_httpx_timeout(timeout_sec)) as client:
        response = client.post(url, json=body)
        response.raise_for_status()
        payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError(f"Ollama returned non-object JSON: {type(payload).__name__}")
    return payload


def unload_model(host: str, model: str, *, timeout_sec: float | None = 60.0) -> dict:
    """Ask Ollama to unload ``model`` immediately (keep_alive=0, empty prompt)."""
    return generate(host, model=model, prompt="", keep_alive=0, timeout_sec=timeout_sec)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_ollama_http_unload.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add worker/router/ollama_http.py tests/test_ollama_http_unload.py
git commit -m "feat(router): add Ollama unload_model HTTP helper"
```

---

### Task 3: `ModelMemoryCache` core (hit / miss / LRU multi-evict / wait)

**Files:**
- Create: `worker/router/model_cache.py`
- Create: `tests/test_model_memory_cache.py`

**Interfaces:**
- Consumes: injectable `unload_fn(host, model) -> None`, `load_fn(host, model) -> None`
- Produces:

```python
class ModelMemoryCache:
    def __init__(
        self,
        *,
        host: str,
        budget_bytes: int,
        model_sizes: dict[str, int],
        unload_fn,
        load_fn,
        wait_timeout_sec: float = 600.0,
    ) -> None: ...

    def ensure(self, model: str) -> None:
        """Block until ``model`` is resident and refcount incremented."""

    def release(self, model: str) -> None:
        """Decrement refcount after a chat finishes (model stays resident)."""

    @property
    def resident(self) -> frozenset[str]: ...

    def used_bytes(self) -> int: ...
```

Semantics must match the spec algorithm (idle LRU eviction; wait when no idle victims).

- [ ] **Step 1: Write failing tests**

Create `tests/test_model_memory_cache.py` with a fake backend:

```python
import threading
import time

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
    sizes = {"a": 4, "b": 4, "c": 6}
    cache = _cache(fake, budget=10, sizes=sizes)
    cache.ensure("a"); cache.release("a")
    cache.ensure("b"); cache.release("b")
    # resident a,b used=8; need c=6 → must evict both idle LRU (a then b) or enough for 6
    cache.ensure("c")
    assert "c" in cache.resident
    assert "a" not in cache.resident or "b" not in cache.resident
    assert fake.unloads  # at least one eviction
    cache.release("c")


def test_ensure_waits_when_only_busy_models_block_space():
    fake = FakeOllama()
    sizes = {"a": 8, "b": 8}
    cache = _cache(fake, budget=10, sizes=sizes)
    cache.ensure("a")  # busy, refcount=1

    done = {"ok": False}

    def other():
        cache.ensure("b")
        done["ok"] = True
        cache.release("b")

    t = threading.Thread(target=other)
    t.start()
    time.sleep(0.2)
    assert done["ok"] is False  # blocked: cannot evict busy a
    cache.release("a")
    t.join(timeout=2.0)
    assert done["ok"] is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_model_memory_cache.py -v`  
Expected: FAIL (module missing)

- [ ] **Step 3: Implement `worker/router/model_cache.py`**

Implement with `threading.Lock` + `threading.Condition`. Track `_entries: dict[str, _Entry]` where `_Entry` has `size`, `refcount`, `last_used` (monotonic). On `ensure`:

1. If resident: refcount++, touch LRU, return.
2. Else while `used + need > budget`: pick idle LRU victims; if none, `condition.wait(timeout)`; on timeout raise `TimeoutError` with a clear message; else unload via `unload_fn`, drop entry.
3. If single model `need > budget`, raise `ValueError` immediately.
4. `load_fn`, insert entry, refcount=1, notify.

On `release`: refcount = max(0, refcount-1); `condition.notify_all()`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_model_memory_cache.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add worker/router/model_cache.py tests/test_model_memory_cache.py
git commit -m "feat(router): add ModelMemoryCache with idle LRU eviction"
```

---

### Task 4: Wire cache into router chat path

**Files:**
- Modify: `worker/router/server.py`
- Modify: `worker/router/__init__.py` if exports needed
- Create/modify tests: prefer a focused unit test that mocks chat HTTP; if none exists, add `tests/test_router_model_cache_wiring.py`

**Interfaces:**
- Consumes: `ModelMemoryCache`, `ollama_http.unload_model`, load via `ollama_http.chat(..., messages=[{"role":"user","content":"ping"}], keep_alive=-1)`
- Produces: `start_router_server(..., model_cache: ModelMemoryCache | None = None)` (or a `dict[str, ModelMemoryCache]` keyed by host). When cache is not None, before `_ollama_chat_with_recovery`: `cache.ensure(model)`; always `cache.release(model)` in `finally`; force `chat_kwargs["keep_alive"] = -1` when cache manages residency.

- [ ] **Step 1: Write failing wiring test**

```python
from worker.router.model_cache import ModelMemoryCache


def test_cache_ensure_release_around_chat(monkeypatch):
    events = []

    class DummyCache:
        def ensure(self, model):
            events.append(("ensure", model))

        def release(self, model):
            events.append(("release", model))

    # Prefer extracting a small helper from server.py if easier to test:
    # run_chat_with_cache(cache, model, chat_fn) -> result
    from worker.router import server as router_server

    def chat_fn():
        events.append(("chat",))
        return {"message": {"content": "ok"}}

    result = router_server._run_cached_chat(DummyCache(), "qwen3:8b", chat_fn)
    assert result["message"]["content"] == "ok"
    assert events == [("ensure", "qwen3:8b"), ("chat",), ("release", "qwen3:8b")]
```

If extracting `_run_cached_chat` is cleaner than spinning `ThreadingHTTPServer`, do that.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_router_model_cache_wiring.py -v`  
Expected: FAIL

- [ ] **Step 3: Implement wiring**

1. Add `_run_cached_chat(cache, model, chat_fn)` helper.
2. In the `/api/chat` handler, after `router.acquire` and before HTTP chat, if `self.model_cache is not None` (or host-specific cache), wrap the chat call with ensure/release and set `keep_alive=-1`.
3. Plumb `model_cache=` through `start_router_server`.

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/test_router_model_cache_wiring.py tests/test_model_memory_cache.py -q`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add worker/router/server.py tests/test_router_model_cache_wiring.py
git commit -m "feat(router): ensure model cache around chat dispatches"
```

---

### Task 5: Stop forcing `MAX_LOADED=1`; raise ceiling for cache

**Files:**
- Modify: `worker/fleet/setup.py` (`effective_max_loaded_models`)
- Modify: `tests/test_fleet_setup.py` (any assertions expecting `1` on overflow)

**Interfaces:**
- Produces: `effective_max_loaded_models(cfg) -> int` returns `max(cfg.model_count, 1)` (or env override), **not** `1` for non-`warm_stack`.

- [ ] **Step 1: Write/adjust failing test**

```python
from worker.fleet.config import FleetConfig
from worker.fleet.setup import effective_max_loaded_models


def test_effective_max_loaded_models_allows_full_stack_on_overflow(monkeypatch):
    monkeypatch.delenv("OLLAMA_MAX_LOADED_MODELS", raising=False)
    cfg = FleetConfig(
        num_servers=1,
        parallel=2,
        max_slots=2,
        memory_tier="vram_overflow",
        model_count=5,
    )
    assert effective_max_loaded_models(cfg) == 5
```

- [ ] **Step 2: Run to verify fail if old behavior**

Run: `.venv/bin/python -m pytest tests/test_fleet_setup.py -k max_loaded -v`  
Expected: FAIL on `== 5` if still returning 1

- [ ] **Step 3: Implement**

```python
def effective_max_loaded_models(cfg: FleetConfig) -> int:
    raw = os.environ.get("OLLAMA_MAX_LOADED_MODELS", "").strip()
    if raw:
        try:
            return max(1, int(raw))
        except ValueError:
            pass
    return max(1, int(cfg.model_count or 1))
```

Update README line that says overflow defaults to `MAX_LOADED=1`.

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/test_fleet_setup.py -q`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add worker/fleet/setup.py tests/test_fleet_setup.py worker/README.md
git commit -m "fix(fleet): do not cap OLLAMA_MAX_LOADED_MODELS to 1 on overflow"
```

---

### Task 6: Conditional pre-warm in bench (and serve warm-all)

**Files:**
- Modify: `worker/bench.py`
- Modify: `worker/serve.py`
- Create: `tests/test_bench_prewarm_gate.py`
- Optionally small helper in `worker/ollama_bootstrap.py`: `def should_prewarm(*, model_sizes: dict[str, int], budget_bytes: int) -> bool`

**Interfaces:**
- Produces: `should_prewarm(model_sizes, budget_bytes) -> bool` True iff `sum(sizes.values()) <= budget_bytes` and budget > 0 and every size > 0.
- Bench: after fleet + sizes known, if `should_prewarm` and not `args.no_warm_models`, warm; else log skip and continue.
- Serve: same gate when `AUTOANNOTATION_OLLAMA_WARM_ALL` is on.
- Construct `ModelMemoryCache` with `cache_budget_bytes(spec, user_budget_gb=...)` and per-model sizes from `worker.fleet.models._model_size_bytes` (or public wrapper), pass into `start_router_server`.

- [ ] **Step 1: Write failing gate test**

```python
from worker.ollama_bootstrap import should_prewarm


def test_should_prewarm_only_when_full_stack_fits():
    sizes = {"a": 3, "b": 3, "c": 3}
    assert should_prewarm(model_sizes=sizes, budget_bytes=10) is True
    assert should_prewarm(model_sizes=sizes, budget_bytes=8) is False
```

- [ ] **Step 2: Run to verify fail**

Run: `.venv/bin/python -m pytest tests/test_bench_prewarm_gate.py -v`  
Expected: FAIL

- [ ] **Step 3: Implement gate + wire bench/serve**

```python
def should_prewarm(*, model_sizes: dict[str, int], budget_bytes: int) -> bool:
    if budget_bytes <= 0 or not model_sizes:
        return False
    if any(size <= 0 for size in model_sizes.values()):
        return False
    return sum(model_sizes.values()) <= budget_bytes
```

In `bench.py` around the existing warm block:

```python
sizes = {name: models._model_size_bytes(name, host=primary_host) for name in required}
budget = sizing.cache_budget_bytes(spec, user_budget_gb=...)
if not args.no_warm_models and should_prewarm(model_sizes=sizes, budget_bytes=budget):
    _progress(f"Pre-warming {len(required)} model(s) (stack fits budget)...")
    warm_all_models(...)
else:
    _progress(
        f"Skipping pre-warm: stack needs "
        f"{sum(sizes.values()) / 1024**3:.1f} GiB, budget "
        f"{budget / 1024**3:.1f} GiB; loading on demand via model cache"
    )
```

Build cache + pass to router start. Use `unload_fn=ollama_http.unload_model` and `load_fn` that pings with `keep_alive=-1`.

Mirror the gate in `serve.py` for optional warm-all.

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/test_bench_prewarm_gate.py tests/test_model_memory_cache.py tests/test_fleet_sizing_cache_budget.py -q`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add worker/ollama_bootstrap.py worker/bench.py worker/serve.py tests/test_bench_prewarm_gate.py
git commit -m "feat(worker): prewarm only when full model stack fits cache budget"
```

---

### Task 7: Docs + regression gate

**Files:**
- Modify: `USAGE.md` (bench keep-alive / warm notes — brief)
- Modify: `worker/README.md` (cache + MAX_LOADED behavior)
- Modify: `docs/superpowers/specs/2026-08-11-router-model-memory-cache-design.md` only if implementation drift needs a one-line note

- [ ] **Step 1: Update operator docs** to state: overflow machines skip pre-warm; router cache loads/evicts via Ollama unload API; budget is 90% VRAM+RAM capped by `WORKER_MODEL_MEMORY_BUDGET_GB`.

- [ ] **Step 2: Run full related suite**

Run:

```bash
.venv/bin/python -m pytest \
  tests/test_fleet_sizing_cache_budget.py \
  tests/test_fleet_sizing.py \
  tests/test_fleet_setup.py \
  tests/test_ollama_http_unload.py \
  tests/test_model_memory_cache.py \
  tests/test_router_model_cache_wiring.py \
  tests/test_bench_prewarm_gate.py \
  tests/test_ollama_keep_alive.py \
  -q
```

Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add USAGE.md worker/README.md
git commit -m "docs: describe router model memory cache behavior"
```

---

## Spec coverage check

| Spec requirement | Task |
|------------------|------|
| 10% VRAM + 10% RAM headroom, user GB cap | Task 1 |
| Unload via Ollama `keep_alive=0` API | Task 2 |
| Idle LRU multi-evict; wait if all busy | Task 3 |
| Router wraps chat with ensure/release | Task 4 |
| No `MAX_LOADED=1` default on overflow | Task 5 |
| Pre-warm only if stack fits | Task 6 |
| Operator docs | Task 7 |

## Placeholder scan

No TBD/TODO steps; each task has concrete tests, commands, and code.
