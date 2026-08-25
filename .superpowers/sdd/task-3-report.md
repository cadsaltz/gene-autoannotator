# Task 3 Report: Add `worker run` one-shot mode

**Date:** 2026-08-24  
**Branch:** `redesign/cloud-backend-hpc-dispatcher`  
**Commit:** `feat(worker): add one-shot run mode for Slurm allocations`

## Summary

Implemented a one-shot worker mode for scheduler allocations. `worker run`
either registers and makes exactly one backend claim or reads an already
materialized job payload, executes that job through `WorkerRuntime` and the
existing annotation subprocess path, reports progress, completes or fails the
backend job, and exits.

## Changes

### `worker/run.py`

- Added `--claim-one` orchestration: register, claim with one free slot, and
  return 0 immediately when the backend returns no job.
- Added `--job-file` orchestration for `{ "job_id": ..., "request": ... }`
  payloads without registration or claiming.
- Added a finite one-job `JobSource` used by `WorkerRuntime`.
- Reports progress through `ProgressReporter`, flushes pending progress before
  completion/failure, and returns 1 when annotation fails.

### `worker/runtime.py`

- Centralized request validation and subprocess dispatch in
  `execute_annotation_job`.
- Serve, bench, and run now use this shared execution function.

### `worker/__main__.py`

- Added the `run` subcommand.
- Added a required mutually exclusive choice between `--claim-one` and
  `--job-file PATH`.
- Preserved worker subprocess cleanup and exit code 130 on interruption.

### `worker/README.md`

- Expanded the mode table to serve / run / bench.
- Documented both one-shot invocations, empty-queue behavior, and the job-file
  schema.

## TDD Evidence

1. Empty queue test first failed during collection because `worker.run` did not
   exist; after the minimal implementation it passed.
2. Claimed-job completion, annotation failure, and job-file tests then failed
   against the minimal implementation; after runtime wiring all four tests
   passed.
3. CLI dispatch tests failed because argparse only accepted serve/bench; after
   adding the subcommand all six Task 3 tests passed.

## Verification

```text
.venv/bin/python -m pytest tests/test_worker_run_claim_one.py -q
6 passed

ReadLints (all edited Python files)
No linter errors found

.venv/bin/python -m pytest -q
755 passed, 10 skipped, 33 failed
```

The full suite failures are outside Task 3: unavailable external model/Ollama
services and existing repository expectation drift in embed, LLM, gene-name,
fleet sizing, bench, and serve tests. The focused Task 3 suite is green.

## Self-review

- Claim mode calls `claim` exactly once and never enters a backend claim loop.
- Empty claims do not instantiate the runtime or execute annotation.
- Job-file mode never calls register or claim.
- Both paths use one runtime slot and the shared subprocess-backed executor.
- Runtime failures invoke backend `fail` with the existing retryability policy
  and produce a nonzero process exit.
- No Task 4 dispatcher or Slurm submission behavior was added.

## Concerns

- `run` assumes the allocation environment has already provisioned the local
  Ollama execution environment, as required by the scheduler launcher; this
  task only adds one-shot backend orchestration.
- Backend transport errors while registering, claiming, completing, or failing
  remain fatal and surface as process errors, matching existing worker client
  behavior.
