# Task 3 report: tie-break fixture assembly

## Status

Complete. The 32 generated candidate cases were merged into the versioned
fixture, validated, covered by focused tests, documented in the protocol, and
committed.

## Commit

- `3af8a41 feat(paper): fill tie-break fixture from subagent-generated candidates`
- Base supplied for this task: `0edad03f83147019f1af3df08401f2950d5c4a2e`

## Implemented

- Added `experiments/paper/runners/tiebreak_fixture.py`:
  - `load_tiebreak_fixture(path)` loads and checks the fixture wrapper.
  - `filter_cases(items, experiment_tags)` requires all requested tags.
  - `validate_case(case)` enforces candidate shape, exact-majority,
    paraphrase-path, null-split, and extractor-0-minority rules.
- Added `experiments/paper/tests/test_tiebreak_fixture.py` with eight focused
  tests covering fixture composition and each validator behavior.
- Merged all 32 locked briefs and generated candidate files into
  `experiments/paper/fixtures/constructed/tiebreak_consensus_v1.json`.
- Preserved every locked `expected` and `agreement` value.
- Updated both tie-break experiment rows in `experiments/paper/PROTOCOL.md`
  from `planned` to `fixtures-ready` and added a revision-log entry.

## Candidate validation repairs

Initial validation found seven candidate-wording issues. Only candidate field
wording in the merged fixture was changed:

- `general-exact-majority-002`: made extractor 0 clearly fail the soft match.
- `general-nonsense-paraphrase-003`
- `biology-paraphrase-majority-007`
- `biology-nonsense-paraphrase-001`
- `biology-nonsense-paraphrase-002`
- `biology-nonsense-paraphrase-003`
- `biology-nonsense-paraphrase-004`

For the six paraphrase cases, majority wording was minimally adjusted so the
intended pair reaches `token_jaccard >= 0.35` while avoiding an exact majority.

## Verification

TDD red check:

- Focused test collection failed with the expected
  `ModuleNotFoundError` before `tiebreak_fixture.py` existed.

Final command:

```text
/home/caden-saltzberg/projects/sch/gene-autoannotator/.venv/bin/python \
  -m pytest experiments/paper/tests/test_tiebreak_fixture.py -v
```

Result:

- `8 passed in 1.30s`
- Independent fixture audit: `32/32 valid`
- Every case returned `validate_case(case) == []`.
- Locked `expected` and `agreement` values matched the briefs.
- `git diff --check` passed.
- IDE diagnostics reported no linter errors in the new Python files.

## Remaining worktree state

- `experiments/paper/fixtures/constructed/generated_raw/` remains untracked as
  requested and was not included in the commit.
- `.superpowers/sdd/task-2-report.md` was already modified before this task and
  was left untouched and uncommitted.
- This report was written after the implementation commit, so it is also not
  included in `3af8a41`.

## Review follow-up: paraphrase Jaccard majority-pair rule

Addressed the Important Task 3 review finding: paraphrase validation now
requires `token_jaccard >= 0.35` among **non-minority (majority) candidates**
only, not across all three candidate pairs.

### Code changes

- Added `_extractor_zero_is_minority(case)` to centralize agreement/notes checks.
- Added `_majority_candidate_values(...)`:
  - When extractor 0 is minority, majority pool = `candidates[1:]` (indices 1–2).
  - Otherwise, majority pool = candidates that `match_soft` to `expected`.
  - If soft-match finds fewer than two majors, fall back to agreement shape:
    drop the candidate with lowest token-jaccard to `expected`.
- `validate_case` paraphrase check now pairs only within the majority pool.
- Error message updated to say "majority candidate pair".

### Regression tests

- `test_validate_paraphrase_requires_majority_pair_not_minority_bridge`:
  synthetic case where minority↔majority Jaccard passes (0.429) but
  majority↔majority fails (0.0); `validate_case` reports an error.
- `test_all_fixture_cases_validate`: all 32 merged fixture cases return `[]`.

### Verification

```text
/home/caden-saltzberg/projects/sch/gene-autoannotator/.venv/bin/python \
  -m pytest experiments/paper/tests/test_tiebreak_fixture.py -v
```

Result: `10 passed in 2.03s`

All 32 fixture cases still validate cleanly under the corrected rule — no
candidate wording changes were required.
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
