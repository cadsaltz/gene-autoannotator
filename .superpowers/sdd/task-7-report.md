# Task 7 Report: Cloud backend and SCRI dispatcher deploy path

**Status:** Complete

## Implementation

- Added `docs/deploy-cloud-backend-hpc-dispatcher.md` for the cloud
  frontend/backend, managed/private MongoDB, SCRI scrontab dispatcher, one-shot
  Slurm workers, optional laptop capacity, verification, and rollback tag.
- Documented the pull-only architecture and singular backend queue in the root
  README, replacing stale production in-process and single-worker claims.
- Updated Compose to use the preferred `BACKEND_API_BASE_URL`.
- Moved the Compose SQLite data mount away from `/app/coordinator` so a durable
  volume cannot retain stale packaged Python code across image rebuilds.
- Recorded that Task 9 account authentication is pending lead confirmation and
  that the worker bearer token is not end-user authentication.

## Verification

- Parsed `deploy/compose/docker-compose.coordinator.yml` with PyYAML and checked
  the `/state/coordinator` persistence path and frontend backend URL.
- `.venv/bin/pytest -q tests/test_backend_url_alias.py tests/test_dispatcher_loop.py`
- Result: 9 passed.

## Concerns / follow-up

- Public account/auth policy remains intentionally unresolved until lead
  confirmation in Task 9. Restrict deployment to trusted users or apply an
  external access boundary meanwhile.
- `GET /jobs/queue-summary` is read-only but currently public; dispatcher
  requests include the worker bearer token, but the endpoint does not enforce
  it.
- The Compose and Python package retain the `coordinator` filename/name until
  the separately scoped Task 8 rename.

## Commit

- `docs: deploy guide for public backend and HPC dispatcher`
