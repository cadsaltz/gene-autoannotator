# Router Model Memory Cache

**Date:** 2026-08-11  
**Status:** approved  
**Owner:** worker / router  

## Problem

Bench pre-warms every required model with a long `keep_alive`. On machines that cannot hold the full performance stack (`vram_overflow` / `swap`), Ollama returns HTTP 500 (“model requires more system memory…”) and the worker exits before jobs start.

Separately, `OLLAMA_MAX_LOADED_MODELS=1` forces a one-model-at-a-time policy. That is not what we want: memory should behave like a **cache** of recently used models.

## Goals

1. Treat VRAM + system RAM as a model weight cache with headroom.
2. Keep as many recently used models resident as the budget allows.
3. Evict only **idle** models (not in an active chat), **LRU first**, and only when loading another model needs space (evict one or many as needed).
4. If every loaded model is in use and space is still insufficient, **wait** until a model becomes idle, then evict.
5. Pre-warm **only** when the full required stack fits in the cache budget; otherwise load on demand.
6. Cap the cache budget at `WORKER_MODEL_MEMORY_BUDGET_GB` when set (and still apply machine headroom).

## Non-goals

- Perfect accounting of KV-cache / concurrent-slot overhead inside the cache (tracked separately by fleet parallel / context sizing).
- Multi-host coordinated cache in v1 (per-Ollama-backend cache is enough; start with single-server correctness).
- Replacing Ollama’s internal allocator; we orchestrate load/unload via its API.

## Unload / load mechanism (Ollama API)

The router does **not** free process memory itself. Ollama owns residency; the router only decides policy and issues API calls:

- **Unload:** `POST /api/generate` with `{"model": "<name>", "keep_alive": 0}` (empty prompt), or chat with empty `messages` + `keep_alive: 0`, or `ollama stop <name>`. Response includes `done_reason: "unload"`.
- **Load / pin:** chat/generate with `keep_alive: -1` (or forever alias) so Ollama does not timer-evict under the cache.
- **Inspect:** `GET /api/ps` (`ollama ps`) to reconcile residents after load/unload.

So: router = cache policy; Ollama = load/unload executor.

## Budget

```
machine_budget =
  sum_i(vram_i * 0.90)           # 10% VRAM headroom
  + system_ram * 0.90            # 10% RAM headroom

cache_budget = min(machine_budget, WORKER_MODEL_MEMORY_BUDGET_GB)
             # if budget unset / -1 → machine_budget only
```

Notes:

- Today’s sizing uses 15% VRAM headroom and **50%** of RAM for models. This design changes both to **10% headroom on VRAM and RAM** (i.e. 90% of each pool is usable for the model cache). Fleet feasibility / tier classification should use the **same** budget helper so warm/skip decisions and cache capacity agree.
- `WORKER_MODEL_MEMORY_BUDGET_GB` remains an optional upper cap (`-1` / omit = no user cap).

## Model sizes

- Prefer measured / manifest sizes already used by fleet footprints (`W_peak` per model or `ollama show` / list API size).
- Cache residency cost for model `M` ≈ that size (weights). Do not double-count KV in the cache map in v1; fleet parallel already constrains concurrent chats.

## Runtime algorithm (per chat request for model M)

Router (before forwarding chat to Ollama):

1. Acquire cache lock for the target backend.
2. If `M` is resident: `refcount++`, update `last_used`, release lock enough to run chat, then `refcount--` on completion (keep resident).
3. If not resident:
   - Let `need = size(M)`, `used = sum(size of residents)`, `free = budget - used`.
   - While `free < need`:
     - Let victims = residents with `refcount == 0`, ordered by `last_used` ascending (LRU).
     - If no victims: **wait** on a condition variable until some resident’s refcount hits 0 (or timeout → fail the request with a clear error).
     - Else unload victims in LRU order (Ollama unload / `keep_alive=0` ping or delete-runner API as used elsewhere) until `free >= need` or victims exhausted; if still short after all idle evicted, wait again (a busy model must finish).
   - Load `M` (minimal chat or explicit load), add to map, `refcount++`, update `last_used`.
4. Run the actual chat with `keep_alive` set so Ollama does **not** timer-evict under the cache (recommend `-1` / forever while the cache owns residency).
5. On chat end: `refcount--`; do not unload.

Concurrency: one cache coordinator per Ollama backend; chat execution may be parallel up to fleet `parallel`, but load/evict decisions are serialized on the cache lock.

## Pre-warm policy

```
if sum(size(required_models)) <= cache_budget:
    warm all required models into the cache (refcount 0 after warm)
else:
    skip pre-warm; log that models will load on demand via the cache
```

`--no-warm-models` remains a hard force-skip.  
`--keep-alive` / `OLLAMA_FLEET_KEEP_ALIVE` may still exist for compatibility, but **cache-managed paths** should pin with forever keep_alive so the cache is the source of truth for unload.

## OLLAMA_MAX_LOADED_MODELS

Stop defaulting non-`warm_stack` fleets to `1`.

Set `OLLAMA_MAX_LOADED_MODELS` to at least the number of required models (or a high ceiling) so Ollama does not fight the router cache with a count cap. Eviction ownership: **router cache**.

## Integration points

| Area | Change |
|------|--------|
| `worker/fleet/sizing.py` | Budget helpers: 10% headroom on VRAM and RAM; shared `cache_budget_bytes(...)`. |
| `worker/fleet/setup.py` | `effective_max_loaded_models` no longer forces `1` for overflow/swap. |
| `worker/router/` | New `ModelMemoryCache` (or equivalent); hook before chat in router server. |
| `worker/bench.py` / `serve.py` | Pre-warm only when full stack fits; pass budget + model sizes into router. |
| Unload helper | Shared utility to unload a named model on a host (existing patterns in fleet/models). |

## Failure modes

| Case | Behavior |
|------|----------|
| Single model larger than budget | Fail fast at ensure/warm/first-load with a clear error (cannot fit even alone). |
| Wait timeout (all models busy forever) | Fail the waiting request; log victims/in-use set. |
| Ollama unload/load 500 | Surface error; optional one retry after re-querying `ollama ps`. |
| Disk / pull missing model | Unchanged (`ensure_models` before batch). |

## Testing

- Unit: budget math (10% VRAM + 10% RAM, user cap).
- Unit: cache — hit, miss+load, LRU multi-evict, wait when all busy, then proceed.
- Unit: pre-warm skipped when `sum(sizes) > budget`, performed when fits.
- Integration/smoke: bench on overflow-sized fake budget does not call warm-all; first chats trigger load/evict without process crash.

## Rollout

1. Implement cache + budget helpers + skip-warm gate.
2. Default on for bench and serve router paths.
3. Rebuild worker Docker image; verify laptop `vram_overflow` run starts jobs without warm OOM.

## Open follow-ups (out of v1)

- Per-slot KV reservation inside the cache budget.
- Multi-GPU / multi-server cache placement.
- Metrics: hit rate, evict count, wait time in bench report.
