# Final whole-branch review fixes

## 2026-09-11

- Fixed the Apptainer read-only worker env failure. The worker-run entrypoint
  now copies `WORKER_ENV_FILE` to an allocation-local writable file under
  `${TMPDIR:-/tmp}` and points Python at the copy. The original read-only mount
  remains available to Apptainer's `--env-file` injection.
- Added a shell-level regression test that invokes the entrypoint with a
  mode-`0444` env file, verifies Python receives a different writable path,
  mutates the copy, and confirms the mounted source is unchanged.
- Restored `DISPATCHER_MAX_INFLIGHT=0` as an emergency stop: launch planning
  now returns zero submissions when the configured maximum is zero.
- Kept bounded-drain claim semantics unchanged. A backend `204` remains an
  authoritative empty-queue latch, while claim exceptions abort the allocation.
  The accepted trade-off is documented in code because retrying at the current
  runtime cadence would be an unbounded tight loop during backend outages.

Verification:

```text
$ pytest tests/test_dispatcher_loop.py tests/test_worker_run_claim_one.py tests/test_worker_run_entrypoint.py
collected 24 items
tests/test_dispatcher_loop.py ....                                       [ 16%]
tests/test_worker_run_claim_one.py ...................                   [ 95%]
tests/test_worker_run_entrypoint.py .                                    [100%]
24 passed in 1.86s
```

Shell checks:

```text
bash -n deploy/docker/worker-run-entrypoint.sh deploy/scripts/run-worker-run.sh
run-worker-run.sh ... --dry-run
exit 0; command retains /app/worker.env:ro and --env-file for injection
```
