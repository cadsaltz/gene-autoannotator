# Task 2 Report: Harden atomic claim for multi-claimer fleets

## Status: DONE

## Summary

Proved that two concurrent fleet claimers cannot double-assign one queued job.
The existing `BEGIN IMMEDIATE` transaction serializes selection and transition,
and the update now additionally requires the selected row to remain queued.
Added a read-only queued-job count and exposed it through
`GET /jobs/queue-summary` without changing job status.

## Changes

### Atomic fleet claim

- Kept `JobStore.assign_job_to_worker(worker_id, *, lease_seconds)` as the only
  API fleet claim path.
- Documented why `BEGIN IMMEDIATE` prevents concurrent claimers from selecting
  the same queued job.
- Added `AND status = 'queued'` to the assignment update as a defensive
  transition guard.

### Read-only queue peek

- Added `JobStore.count_queued_jobs() -> int`.
- The helper performs only `SELECT COUNT(*)` for `status = 'queued'`.
- Added pull-only `GET /jobs/queue-summary`, returning `{"queued": <count>}`.
- Documented that peek endpoints do not transition status.

### Tests

- Added `tests/test_job_claim_race.py`.
- Concurrent test starts two claimers against one SQLite database and asserts
  exactly one receives the job.
- Store-level peek test verifies the count and both involved statuses.
- API-level peek test verifies the response and that the queued job stays
  queued.

## TDD Evidence

1. Added all three focused tests first.
2. Initial run: the concurrency test passed against the existing serialized
   transaction; the helper test failed with missing `count_queued_jobs`, and
   the endpoint test failed with HTTP 404.
3. Added the minimal helper, endpoint, claim documentation, and defensive
   status predicate.
4. Focused rerun passed: 3 tests.

## Verification

- `.venv/bin/pytest tests/test_job_claim_race.py -v`: 3 passed.
- `.venv/bin/pytest tests/test_job_claim_race.py tests/test_coordinator_job_store.py tests/test_coordinator_claim_bias.py tests/test_worker_integration.py tests/test_coordinator_api.py -q`:
  90 passed.
- IDE diagnostics for all modified Python files: no errors.

## Self-Review

- Confirmed the race test waits on both futures and examines both results.
- Confirmed every fleet API assignment still calls
  `assign_job_to_worker`; no alternate claim path was added.
- Confirmed the queue-summary route is declared before `/jobs/{job_id}`.
- Confirmed both peek tests verify status preservation.
- Confirmed no dispatcher or later-task functionality was implemented.
- Confirmed unrelated changes in `.superpowers/sdd/task-3-report.md` and
  `experiments/` remain untouched.

## Concerns

None.

## Important Review Fixes

- Added a two-party barrier to the concurrent claim test so both worker threads
  reach the claim call before either proceeds.
- Added a regression test that forces the guarded assignment update to affect
  zero rows and verifies the store returns `None` while leaving the job queued.
- `assign_job_to_worker` now checks that the guarded update changed exactly one
  row before returning the selected job.

### Fix Evidence

1. RED:
   `.venv/bin/pytest tests/test_job_claim_race.py::test_assign_job_returns_none_when_guarded_update_loses_race -v`
   failed because `assign_job_to_worker` returned the still-queued job after the
   trigger forced the guarded update to affect zero rows.
2. GREEN:
   `.venv/bin/pytest tests/test_job_claim_race.py -v` passed all 4 tests.
3. RELATED:
   `.venv/bin/pytest tests/test_job_claim_race.py tests/test_coordinator_job_store.py tests/test_coordinator_claim_bias.py tests/test_worker_integration.py tests/test_coordinator_api.py -q`
   passed all 91 tests.
4. IDE diagnostics reported no errors in the modified Python files.
