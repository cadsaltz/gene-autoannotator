# Task 2 Report: Phase B — fail-closed worker token

## Status

**Complete.** Implemented, tested, and committed on `feat/passwordless-otp-accounts`.

## Commit

- `f99d32e19c14cbae446f69376930439896999567` — fix: fail closed when worker API token required but unset

## What changed

### `backend/api.py`

Extended `_require_worker_token` inside `create_app` to read `REQUIRE_WORKER_API_TOKEN` via existing `_env_flag` (default `False`). When the flag is true and `worker_token` is unset/empty, worker-protected routes now return **503** with detail `WORKER_API_TOKEN is required but not configured.` instead of allowing unauthenticated access. When the flag is false and no token is configured, behavior is unchanged (routes remain open). When a token is configured, Bearer validation still returns **401** on mismatch.

### `coordinator.env.example`

Documented `REQUIRE_WORKER_API_TOKEN=0` with a comment to set `1` on internet-facing deploys.

### `tests/test_coordinator_api.py`

Added two tests per the plan:

- `test_worker_routes_fail_closed_when_token_required_but_unset` — `REQUIRE_WORKER_API_TOKEN=1`, no token → 503 on `GET /jobs/queue-summary`
- `test_worker_routes_still_open_when_token_not_required_and_unset` — `REQUIRE_WORKER_API_TOKEN=0`, no token → 200

## TDD evidence

1. Added tests first; `test_worker_routes_fail_closed_when_token_required_but_unset` failed (200 vs expected 503) before implementation.
2. After implementation, targeted and `-k worker` runs passed.

## Test results

```text
pytest tests/test_coordinator_api.py::test_worker_routes_fail_closed_when_token_required_but_unset \
       tests/test_coordinator_api.py::test_worker_routes_still_open_when_token_not_required_and_unset \
       tests/test_coordinator_api.py -k worker -v
→ 7 passed, 61 deselected
```

Includes existing worker-related tests (`test_worker_endpoints_require_token`, etc.).

## Self-review

**Correctness:** Logic matches the brief: fail-closed only when both `REQUIRE_WORKER_API_TOKEN` is enabled and `worker_token` is falsy. Empty string token from env would also trigger fail-closed when required, which is desirable.

**Scope:** Minimal diff; reuses `_env_flag` and closure `worker_token` like `WORKER_CAPACITY_REQUIRED`. No change to production default module-level `app = create_app(...)` unless deploy sets the new env var.

**Gaps / follow-ups:**

- Production compose/deploy templates were not updated to set `REQUIRE_WORKER_API_TOKEN=1`; operators must opt in via env (as documented in `coordinator.env.example`). A later task may wire this into Docker/compose for public deploys.
- `USAGE.md` still describes unset token as “unauthenticated” without mentioning `REQUIRE_WORKER_API_TOKEN`; optional doc sync in a docs pass.
- Tests use explicit `worker_api_token=None` plus cleared `WORKER_API_TOKEN` env; this matches how tests construct apps and avoids leaking host env.

**Risk:** Low. Default remains backward-compatible (`REQUIRE_WORKER_API_TOKEN` defaults off). Misconfiguration surfaces as 503 (service unavailable) rather than silent open worker API.
