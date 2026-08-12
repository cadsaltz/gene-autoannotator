# Task 3 Report: ModelMemoryCache Core

## Status

Complete.

## Commit

- `ac755ff feat(router): add ModelMemoryCache with idle LRU eviction`

## Changes

- Added `worker/router/model_cache.py`.
  - Serializes residency decisions with `threading.Lock` and `threading.Condition`.
  - Tracks model size, active reference count, and monotonic last-use time.
  - Reuses resident models without reloading and increments their reference count.
  - Loads cache misses through an injected backend function.
  - Evicts one or more idle residents in LRU order until the requested model fits.
  - Waits for busy residents to become idle when no eviction candidate exists.
  - Uses a single wait deadline and raises a clear `TimeoutError` listing busy models.
  - Rejects a model larger than the total cache budget before any backend call.
  - Keeps released models resident and wakes waiting callers.
  - Exposes thread-safe `resident` and `used_bytes()` views.
- Added `tests/test_model_memory_cache.py` verbatim from the task brief, using
  injected fake load and unload functions rather than real Ollama calls.

## TDD Evidence

1. Added the three brief tests before production code.
2. Ran the targeted test command and observed collection fail with
   `ModuleNotFoundError: No module named 'worker.router.model_cache'`.
3. Implemented the minimal cache core.
4. Re-ran the targeted tests successfully.

## Verification

- Targeted:
  - Command: `PYTHONPATH=<worktree> <repo>/.venv/bin/python -m pytest tests/test_model_memory_cache.py -v`
  - Result: `3 passed in 0.22s`
- Full worktree suite:
  - Command: `PYTHONPATH=<worktree> <repo>/.venv/bin/python -m pytest`
  - Result: `7 passed in 0.33s`
- IDE diagnostics for both changed files: no linter errors.

## Concerns

- None within Task 3 scope.
- Backend load and unload calls intentionally execute while holding the cache
  lock so residency decisions remain serialized, as specified.

## Important Review Fixes

- Strengthened the LRU eviction test so a 7-byte model must evict both 4-byte
  idle residents under a 10-byte budget, and asserted unload order `a`, then
  `b`.
- Replaced the scheduling-dependent sleep in the busy-model wait test with a
  `threading.Event` triggered when the waiter enters the condition wait, then
  asserted it remains blocked until the busy model is released.
- Targeted command:
  `PYTHONPATH=/home/caden-saltzberg/projects/sch/gene-autoannotator/.worktrees/router-model-memory-cache /home/caden-saltzberg/projects/sch/gene-autoannotator/.venv/bin/python -m pytest tests/test_model_memory_cache.py -v`
- Targeted result: `3 passed in 0.02s`.
