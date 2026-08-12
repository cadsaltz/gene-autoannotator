# Tiered Model Residency Policy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Choose residency mode from how many models fit (largest-first): one-at-a-time, multi-model cache, or full warm stack — and stop forcing `keep_alive=-1`; honor env/`OLLAMA_FLEET_KEEP_ALIVE` (e.g. `5m`). Dashboard residency comes from `ollama ps` behind an easy kill-switch.

**Architecture:** At bench/serve startup, sort required models by size descending and greedily pack into a **pack budget** = `cache_budget_bytes * WORKER_RESIDENCY_PACK_FACTOR` (default **0.70** — 30% wiggle room so KV/spill/fragmentation do not fake a multi-model tier). The pack count selects a **residency mode**. Mode drives `OLLAMA_MAX_LOADED_MODELS`, whether `ModelMemoryCache` wraps chats, and whether to pre-warm. Chat `keep_alive` always follows the existing resolve path (CLI → env → fleet), never hard-coded `-1`. Dashboard IN MEM reads live `/api/ps` (optional; default on, disable via env).

**Tech Stack:** Python worker/router, Ollama `/api/ps` + chat/unload helpers, existing `worker/fleet/sizing.py` budget helpers, pytest.

## Global Constraints

- Ollama **server** pin remains `0.24.0` (`worker/ollama_version.py` / Dockerfile) unless explicitly changed elsewhere.
- Do **not** force `keep_alive=-1` when the model cache is enabled; use resolved fleet/env keep_alive (operator may set `5m`).
- Pack models **largest-first** against **`pack_budget`**, not the raw observable cache budget.
- Default `WORKER_RESIDENCY_PACK_FACTOR=0.70` (30% wiggle). Override via env if needed.
- `WORKER_MODEL_MEMORY_BUDGET_GB` still caps the underlying `cache_budget_bytes` when set.
- Dashboard `ollama ps` probe must be disable-able without code edits (`WORKER_DASHBOARD_OLLAMA_PS=0` or equivalent).
- Prefer small, testable units; TDD for packing/mode selection and keep_alive routing.
- Fix log paths so `worker-bench.log` / `ollama-server-*.log` land on a bind-mounted dir (e.g. under `--output-dir`), not unmounted `/out/`.

---

## File map

| File | Responsibility |
|------|----------------|
| `worker/router/residency.py` (new) | Pack largest-first; pack-factor; classify `ResidencyMode`; pure functions + tests |
| `worker/fleet/setup.py` | `effective_max_loaded_models` takes mode / packed count instead of always `model_count` |
| `worker/router/server.py` | Remove forced `keep_alive=-1`; wire cache only in `cache` mode |
| `worker/bench.py` / `worker/serve.py` | Select mode at startup; apply MAX_LOADED + cache + prewarm; pass keep_alive through |
| `worker/bench_dashboard.py` | IN MEM from `ollama ps` (+ in-flight from router); env kill-switch |
| `worker/router/ollama_http.py` or small `worker/router/ps.py` | Fetch/parse `/api/ps` for dashboard |
| `deploy/scripts/run-worker-bench.sh` | Ensure logs under a mounted path (or document `WORKER_LOG_FILE`) |
| `docs/...` / `USAGE.md` / `worker.env.example` | Document modes + env knobs |
| `tests/test_residency.py` (new) | Packing + mode selection + pack-factor / laptop fixture |
| `tests/test_router_keep_alive.py` or extend server tests | keep_alive not overwritten to `-1` |

---

## Pack budget (wiggle room)

`cache_budget_bytes` (today ~10% VRAM/RAM headroom) is the **observable** ceiling. Residency packing must use a stricter budget:

```
pack_budget = floor(cache_budget_bytes * WORKER_RESIDENCY_PACK_FACTOR)
# default FACTOR = 0.70  → 30% wiggle for KV, CPU spill, fragmentation, dual slots
```

If the multi-model cache is enabled, its runtime `budget_bytes` should also be **`pack_budget`** (same number), so the tier decision and the live cache agree.

### Worked example (this laptop — must classify `single`)

| Model | Size |
|-------|------|
| gemma3:27b | 17.0 GiB |
| qwen3:14b | 9.3 GiB |
| gemma3:12b | 8.1 GiB |
| mistral-nemo:12b | 7.1 GiB |
| qwen3:8b | 5.2 GiB |

Observable `cache_budget` = **35.3 GiB**.

| Factor | Pack budget | Largest-first pack | Mode |
|--------|-------------|--------------------|------|
| 1.00 (no wiggle) | 35.3 | 17+9.3+8.1 = 34.4 (3 models) | `cache` ← too optimistic |
| **0.70 (default)** | **24.7** | **17.0 only** (17+9.3=26.3 > 24.7) | **`single`** ← required |
| 0.75 | 26.5 | 17+9.3 = 26.3 (2 models) | `cache` |

So the default **0.70** is chosen so this machine is `single`. Unit test must lock this fixture in.

---

## Residency modes (spec)

Given required models with sizes, **pack budget** `B` (= `cache_budget * factor`):

1. Sort models by size **descending**.
2. Greedy pack: add next model while `sum(packed) + size <= B`.
3. Classify:

| Condition | Mode | `OLLAMA_MAX_LOADED_MODELS` | `ModelMemoryCache` | Pre-warm |
|-----------|------|---------------------------|--------------------|----------|
| Packed count == 0 (largest alone `> B`) | `single` | `1` | off | no |
| Packed count == 1 (only largest fits) | `single` | `1` | off | no (load on demand) |
| `1 < packed < len(required)` | `cache` | `packed` | on (budget=`B`) | no (on demand into cache) |
| Packed count == len(required) | `warm_stack` | `len(required)` | off | yes (load all once) |

Notes:

- **`single`:** July-like. `parallel` / slots still allow same-model concurrency + paper-fetch overlap.
- **`cache`:** Keep up to what fits under **pack budget**; idle LRU eviction; honor operator keep_alive (e.g. `5m`).
- **`warm_stack`:** Full stack fits under pack budget; skip cache coordinator; optional warm with operator keep_alive.

Edge: if largest `> B`, mode `single` still; first load may fail at Ollama — surface clear error (existing behavior).

---

### Task 1: Pure packing + mode selection

**Files:**
- Create: `worker/router/residency.py`
- Create: `tests/test_residency.py`

- [ ] **Step 1: Write failing tests** for:
  - Sort largest-first packing into budget
  - Only largest fits → `single`, packed=`[largest]`
  - Largest + next fit, not all → `cache`, packed list length 2+
  - All fit → `warm_stack`
  - Empty / zero budget behavior (document: `single`)
  - **Laptop fixture:** sizes above, `cache_budget=35.3GiB`, factor `0.70` → mode `single`, packed=`[gemma3:27b]`
  - Same fixture with factor `1.0` → mode `cache` with 3 models (documents why wiggle exists)

- [ ] **Step 2: Run tests — expect fail**

```bash
.venv/bin/python -m pytest tests/test_residency.py -q --tb=short
```

- [ ] **Step 3: Implement** `pack_budget_bytes(cache_budget, factor=0.70)`, `pack_models_largest_first(...)`, `select_residency_mode(...)` → `ResidencyMode` (`single` | `cache` | `warm_stack`) plus `packed_models` / `max_loaded`. Read factor from `WORKER_RESIDENCY_PACK_FACTOR` when wiring (pure fn takes explicit factor).

- [ ] **Step 4: Run tests — expect pass**

- [ ] **Step 5: Commit**

```bash
git add worker/router/residency.py tests/test_residency.py
git commit -m "$(cat <<'EOF'
feat(router): classify residency mode by largest-first pack with wiggle

EOF
)"
```

---

### Task 2: Stop forcing keep_alive=-1; honor env/fleet

**Files:**
- Modify: `worker/router/server.py` (remove `chat_kwargs["keep_alive"] = -1` when cache present)
- Modify/create tests under `tests/` covering handler keep_alive from env
- Modify: `docs/superpowers/specs/2026-08-11-router-model-memory-cache-design.md` (note superseded keep_alive rule) — short amendment paragraph

- [ ] **Step 1: Write failing test** — with model_cache attached, chat kwargs keep_alive remains `5m` (or env value), not `-1`.

- [ ] **Step 2: Remove forced `-1` overwrite** in `_make_handler` chat path; keep using body/env resolve only.

- [ ] **Step 3: Run targeted tests**

```bash
.venv/bin/python -m pytest tests/test_residency.py tests/test_ollama_keep_alive.py -q --tb=short
# plus any new router keep_alive test file
```

- [ ] **Step 4: Commit**

```bash
git commit -m "$(cat <<'EOF'
fix(router): do not force keep_alive=-1 when model cache is enabled

EOF
)"
```

---

### Task 3: Wire mode into fleet / MAX_LOADED / cache / prewarm

**Files:**
- Modify: `worker/fleet/setup.py` — `effective_max_loaded_models(cfg, *, max_loaded: int | None = None)` or set env before fleet start from mode
- Modify: `worker/bench.py`, `worker/serve.py` — after sizes known, `select_residency_mode`; configure:
  - export/apply `OLLAMA_MAX_LOADED_MODELS` from mode **before** `reset_ollama_fleet` if possible; if fleet already started, document that MAX_LOADED must be set before start (bench already starts fleet earlier — **reorder or pass max_loaded into start_fleet**)
- Modify: cache construction only when mode == `cache`
- Prewarm only when mode == `warm_stack`

**Ordering constraint (important):** Today bench starts the Ollama fleet before building the cache. `OLLAMA_MAX_LOADED_MODELS` is set at `ollama serve` start. Plan must either:

1. Probe sizes + select mode **before** `reset_ollama_fleet`, then pass `max_loaded_models` into fleet start, or
2. Restart fleet after mode selection (avoid if possible).

Prefer (1): move size probe + residency selection before fleet start (sizes from manifest/`ollama show` may need a temporary ollama or use offline manifest estimates already in `worker/fleet/models.py`).

- [ ] **Step 1: Inspect** current bench/serve order; write a short comment in the PR/commit body how MAX_LOADED is applied before serve.

- [ ] **Step 2: Failing test** for `effective_max_loaded_models` / helper returning 1 vs packed vs full count.

- [ ] **Step 3: Implement wiring** in bench + serve; log one clear line:
  `Residency mode=cache packed=3/5 max_loaded=3 budget=35.3GiB keep_alive=5m`

- [ ] **Step 4: Run fleet + residency tests**

- [ ] **Step 5: Commit**

```bash
git commit -m "$(cat <<'EOF'
feat(worker): tier residency single|cache|warm_stack from largest-first pack

EOF
)"
```

---

### Task 4: Dashboard IN MEM via `ollama ps` (kill-switch)

**Files:**
- Create or extend: `worker/router/ollama_ps.py` — `list_resident_models(host) -> list[{name, size_vram, size_ram, ...}]`
- Modify: `worker/bench_dashboard.py` — build IN MEM strip from ps + router in-flight map (dots = in-flight count per model)
- Env: `WORKER_DASHBOARD_OLLAMA_PS=1` default; `0`/`off` → skip ps (show in-flight-only or “ps disabled”)
- Debounce: reuse existing dashboard poll interval; do not add extra per-frame hammering beyond current refresh

- [ ] **Step 1: Unit test** parser for sample `/api/ps` JSON (fixture).

- [ ] **Step 2: Implement fetch + dashboard rendering.**

- [ ] **Step 3: Document kill-switch** in `worker.env.example` + `USAGE.md` one-liner.

- [ ] **Step 4: Commit**

```bash
git commit -m "$(cat <<'EOF'
feat(dashboard): show Ollama residency from /api/ps with kill-switch

EOF
)"
```

---

### Task 5: Persist bench logs on bind mounts

**Files:**
- Modify: `worker/bench.py` `_resolve_log_file` — default to `--output-dir / worker-bench.log` (inside mounted annotations), not parent `/out/`
- Modify: `deploy/scripts/run-worker-bench.sh` if needed so `WORKER_LOG_FILE` defaults correctly
- Ollama tee already follows log dir — ensure `set_ollama_log_dir` uses same mounted directory

- [ ] **Step 1: Change default log path** to `Path(output_dir) / "worker-bench.log"` (or `output_dir.parent / "logs/"` only if that parent is mounted — **prefer inside output-dir**).

- [ ] **Step 2: Smoke** with dry-run path logic unit test if easy.

- [ ] **Step 3: Commit**

```bash
git commit -m "$(cat <<'EOF'
fix(bench): write worker and ollama logs under mounted output-dir

EOF
)"
```

---

### Task 6: Docs + operator checklist

**Files:**
- `worker.env.example`, `deploy/docker/worker.bench.env.example`, `USAGE.md` (Worker bench section), amend cache design spec with “Superseded: keep_alive / mode selection”

Document:

```bash
OLLAMA_FLEET_KEEP_ALIVE=5m          # honored (not overwritten to -1)
WORKER_RESIDENCY_PACK_FACTOR=0.70   # 30% wiggle on cache_budget for tier decision (default)
WORKER_DASHBOARD_OLLAMA_PS=1        # set 0 if ps probes stress Ollama
# residency mode is automatic from pack_budget + model sizes
```

- [ ] **Step 1: Update docs/examples**

- [ ] **Step 2: Commit**

```bash
git commit -m "$(cat <<'EOF'
docs: residency modes, keep_alive, and dashboard ps kill-switch

EOF
)"
```

---

### Task 7: Regression gate

- [ ] **Step 1: Run**

```bash
.venv/bin/python -m pytest tests/test_residency.py tests/test_ollama_keep_alive.py tests/test_fleet_setup.py tests/test_fleet_setup_max_loaded.py tests/test_bench_dashboard.py -q --tb=short
```

(Adjust list to whatever test files exist after implementation.)

- [ ] **Step 2: Manual checklist** (laptop / Docker):
  1. `OLLAMA_FLEET_KEEP_ALIVE=5m` → startup log shows `keep_alive=5m` (not `-1`).
2. Overflow machine with ~35 GiB observable budget + performance stack → mode **`single`** (with default pack factor 0.70); never warm full stack; never multi-model cache.
3. After run, `run/annotations/worker-bench.log` exists on host.
4. Dashboard IN MEM matches `curl localhost:11434/api/ps` when probe enabled; blank/disabled path when `WORKER_DASHBOARD_OLLAMA_PS=0`.

- [ ] **Step 3: Final commit** only if doc/test fixups remain.

---

## Out of scope

- Perfect KV-cache byte accounting
- Multi-host shared cache
- Changing GO resolve behavior
- Reverting Ollama server pin (stays 0.24 unless separate change)

## Success criteria

1. Operator-set `5m` keep_alive is what chats use.
2. Largest-first packing selects `single` | `cache` | `warm_stack` correctly (unit-tested), including the 35.3 GiB / performance-stack → `single` fixture at factor 0.70.
3. Overflow boxes no longer pin ~30 GiB with forever keep_alive.
4. Dashboard residency from `ollama ps`, disable-able.
5. Bench logs survive Docker `--rm` via mounted output-dir.
