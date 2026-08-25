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

- Backend transport errors while registering, claiming, completing, or failing
  remain fatal and surface as process errors, matching existing worker client
  behavior.

## Review follow-up: fleet provisioning and ephemeral capacity

Addressed the Critical/Important Task 3 review findings:

- `--claim-one` still registers and claims before any expensive fleet work, so
  an empty queue exits 0 without probing hardware, launching Ollama, pulling
  models, starting a router, or invoking annotation.
- A claimed job (and `--job-file`) now provisions the local execution stack
  using the same fleet helpers as serve/bench:
  `ensure_worker_env`, `ensure_fleet_config`, `probe_system`,
  `reset_ollama_fleet`, `ensure_models`, `refresh_fleet_footprints`, and
  `start_router_server`. The resulting localhost URL is exported as
  `OLLAMA_ROUTER_URL` before `WorkerRuntime` executes the annotation.
- One-shot claim registration now advertises `max_slots=1` and uses
  `<hostname>-slurm-<SLURM_JOB_ID>` when available, otherwise
  `<hostname>-pid-<pid>`, avoiding collisions with a persistent serve worker.
- Run mode shuts down its router and supervised Ollama fleet on completion or
  failure.

### Review regression tests

The focused suite now covers:

- no-job exit without fleet bootstrap or annotation;
- ephemeral Slurm worker identity and one-slot registration capacity;
- fleet bootstrap invocation before executing a claimed job;
- existing claimed completion/failure, job-file, and CLI dispatch behavior.

```text
.venv/bin/python -m pytest tests/test_worker_run_claim_one.py -q
7 passed

.venv/bin/python -m py_compile worker/run.py tests/test_worker_run_claim_one.py
exit 0
```

An additional related-suite run completed with 32 passing and three pre-existing
failures in `test_worker_serve.py` / `test_worker_bench.py`: the serve fixture
does not materialize `OLLAMA_MAX_LOADED_MODELS`, and two bench tests patch a
removed `models_loaded` symbol. These failures are unchanged by the Task 3
follow-up.

## Medium-finding follow-up: env order and bootstrap failure

Addressed the remaining Medium Task 3 findings:

- `worker run` now calls `ensure_worker_env(interactive=False,
  skip_fleet_config=True)` before `load_config()`. This loads coordinator
  credentials from `worker.env` without provisioning the fleet before the
  one-shot backend claim.
- Fleet bootstrap no longer reloads the worker environment after configuration
  has already been resolved.
- If fleet bootstrap raises after `--claim-one` successfully claims a job, run
  mode reports the job failed with `retryable=True` and exits 1 instead of
  leaving the backend job in the running state.
- Job-file bootstrap errors retain their previous exception behavior because
  that path does not claim a backend job.

### Regression tests

The focused suite now verifies worker-env loading precedes config resolution and
that a post-claim fleet bootstrap error invokes `client.fail`.

```text
.venv/bin/python -m pytest tests/test_worker_run_claim_one.py -q
9 passed

.venv/bin/python -m py_compile worker/run.py tests/test_worker_run_claim_one.py
exit 0
```
