# Phase 2 Task 3 Report: worker claim-up-to-N drain loop

## Status

DONE

## Implementation

- Added a bounded coordinator job source that seeds the first claimed job, claims concurrently up to available runtime slots, and stops after the configured number of claimed jobs or the first empty claim.
- Preserved `--claim-one` as a one-job limit while registering the worker with its configured `max_slots`.
- Added `--claim-max N`, `WORKER_RUN_MAX_JOBS`, and the dispatcher-aligned default of 500, in that precedence order.
- Reused one fleet/router bootstrap for the whole drain and retained retryable failure reporting when bootstrap fails after the initial claim.
- Changed the worker-run container entrypoint to use the default bounded-drain path.
- Removed the one-slot fleet override so `WorkerRuntime` can use fleet/config concurrency.

The chunk limit counts jobs when claimed, including jobs that later fail.

## Tests

- Focused: `17 passed` in `tests/test_worker_run_claim_one.py`.
- Relevant worker/dispatcher suite: `32 passed`.
- Coverage includes N=1 compatibility, N=3 stopping with five jobs available, N=5 stopping on an empty claim after two jobs, configured registration slots, CLI/env/default precedence, heartbeat/cleanup behavior, and retryable bootstrap failure.

## Concerns

None.

## Important review fix

- Changed worker run startup to materialize saved fleet settings before
  `load_config()`, registration, and the initial claim. This makes
  `WORKER_MAX_SLOTS` and its companion fleet keys from `worker.env` or
  `WORKER_ENV_FILE` available when the registration payload is built.
- This configuration load does not start Ollama. The supervised fleet/router
  bootstrap remains deferred until after a non-empty first claim and still
  occurs once for the bounded drain.
- Added an integration-style regression test that points `WORKER_ENV_FILE` at
  a temporary saved configuration and verifies registration and the initial
  claim use its configured seven slots.

## Important review fix tests

- Red check before the implementation: the two focused tests failed because
  fleet configuration was skipped and the initial claim used 20 rather than
  the saved seven slots.
- Focused regression check:
  `.venv/bin/python -m pytest -q tests/test_worker_run_claim_one.py -k 'loads_worker_env_before_config or registers_with_max_slots_from_worker_env_file'`
  — `2 passed, 17 deselected`.
- Full claim-max worker-run test file:
  `.venv/bin/python -m pytest -q tests/test_worker_run_claim_one.py`
  — `19 passed in 1.89s`.
