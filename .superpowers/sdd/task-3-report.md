# Task 3 Report: Phase B — strip client filesystem paths from public jobs

## Status

**Complete.** Implemented with TDD, tested, and committed on `feat/passwordless-otp-accounts`.

## Commit

- `6f0286c24a2bba49997fc7ad0c8c4b7621794e02` — fix: ignore client cache/output paths on public job APIs

## What changed

### `backend/api.py`

- Added module-level server path constants (`SERVER_CACHE_DIR`, `SERVER_OUTPUT_DIR`, `SERVER_GENE_NAME_CACHE`) and `_SERVER_PATH_UPDATES`.
- Added `_server_owned_job_request()`; `POST /jobs` applies it before target resolution and persistence.
- `POST /batches` applies the same overrides via `request.model_copy(update=_SERVER_PATH_UPDATES)` before preview/queueing, so stored batch `options` and materialized per-entry jobs both use server paths.

### `shared/job_contract.py`

- Updated doc comment on `AnnotationJobRequest` path fields: ignored on public API; workers receive server defaults from the coordinator.

### `backend/schemas.py`

- Comment on `BatchJobOptions` path fields that public API ignores client values.

### `tests/test_coordinator_api.py`

- `test_create_job_ignores_client_filesystem_paths` — POST malicious paths, assert persisted request uses `./.cache`, `gen_json`, and server gene-name cache (no `/etc`).

## TDD evidence

1. Added test first; failed with `cache_dir == '/etc/passwd'` before implementation.
2. After overrides in `create_job` / `create_batch`, targeted test passed; full `tests/test_coordinator_api.py` — 69 passed.

## Test results

```text
pytest tests/test_coordinator_api.py::test_create_job_ignores_client_filesystem_paths -v → PASSED
pytest tests/test_coordinator_api.py -q → 69 passed
```

Note: Brief example used `200` and `response.json()['id']`; actual API returns **201** and `job_id` — test matches production contract.

## Self-review

**Correctness:** Client-supplied `cache_dir`, `output_dir`, and `gene_name_cache` never reach the job store on public create endpoints. Batch path fields in stored batch metadata are also normalized because the batch request is copied before `_batch_options_from_request` and `_job_request_for_batch_entry`.

**Scope:** Path stripping only at public queue boundaries; CLI/local callers using `AnnotationJobRequest` directly outside HTTP are unchanged (intentional).

**Gaps / follow-ups:**

- No dedicated batch integration test for path stripping; batch behavior follows the same `model_copy` on `BatchCreateRequest`. Add `test_create_batch_ignores_client_filesystem_paths` if batch regressions become a concern.
- `POST /batches/validate` still accepts path fields in the body (not persisted); harmless unless clients rely on echoing those values.
- Task 8 session gating will require updating the job test to use an authenticated client; test currently uses unauthenticated POST as specified for pre-Task-8 ordering.

**Risk:** Low. Defaults match existing server defaults; no change to worker execution semantics beyond rejecting attacker-controlled paths.
