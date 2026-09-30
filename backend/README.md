# Gene Autoannotator Backend

This directory contains the FastAPI wrapper around the existing Python annotator.
It does not replace the command-line workflow; it imports the existing CLI-level
`autoannotation.__main__.main(...)` function and exposes it through HTTP job,
profile, validation, and annotation-history endpoints.

## Setup

Use the existing project virtual environment if available:

```bash
activatevenv
```

Or create and activate a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Install the existing annotator dependencies and the small web dependency set:

```bash
python -m pip install -r requirements.txt
python -m pip install -r requirements-web.txt
```

Copy the backend environment template to the project root `.env` (loaded
automatically on startup):

```bash
cp backend.env.example .env
```

Edit `.env` as needed — for example set `BACKEND_PUBLIC_URL` to your LAN IP
and configure `WORKER_API_TOKEN` before connecting external workers.

Run the API server:

```bash
uvicorn backend.api:app --host 0.0.0.0 --port 8000
```

On startup the backend logs its listen address, suggested worker
`BACKEND_URL`, token status, and whether the embedded in-process worker is
enabled.

Check that it is reachable:

```bash
curl http://10.158.45.197:8000/healthz
```

`/healthz` is the public liveness probe. The detailed `/health` and
`/backend-info` endpoints require an admin session.

Annotation history writes use MongoDB. Put your local connection string in the
project root `.env` file so completed backend jobs can be saved:

```bash
MONGO_URI=mongodb://localhost:27017/gene_autoannotator
```

Organism profiles are stored as local JSON files under `data/profiles/` (or
`PROFILES_DIR`). MongoDB is not used for profile storage. On first start the
backend seeds that directory from the code catalog in
`autoannotation.organisms.PROFILES`.

The API will still start if MongoDB is unavailable, but `/health` will report
annotation storage as unavailable. Completed jobs will record an annotation
storage warning until the connection is fixed. Profile create/update/delete
only need a writable profiles directory.

The Next.js frontend reads stored annotations directly from MongoDB through its
own `/api/annotations/...` routes. Add the same `MONGO_URI` value to
`frontend/.env.local` so annotation search/review continues to work even when
this FastAPI process is offline.

The annotator's Ollama models can also be configured in `.env`. This is useful
when the backend sees a different model list than the original development
machine:

```bash
AUTOANNOTATION_MODEL_MODE=lite
AUTOANNOTATION_SUMMARY_MODELS=mistral:7b-instruct-v0.2-q3_K_M,llama3.2:3b,gemma3:4b
AUTOANNOTATION_CONSENSUS_MODEL=phi3:3.8b
AUTOANNOTATION_AGGREGATION_MODEL=gemma3:4b
```

If `OLLAMA_HOST` is set in the terminal where the CLI works, add the same value
to `.env` before restarting the backend.

## Real Annotation Requirements

The API still uses the same underlying annotation code. Real jobs require the
same local services, models, network access, and cache/output directories as the
terminal command, including Ollama and the configured LLM models.

Job and validation requests require either `profile` or `organism`, and either
`name` or `locus`. `profile` selects a local saved profile;
`organism` with optional `strain` builds an ad hoc profile for one submission.
Supplying both name and locus gives the target resolver the strongest evidence,
but name-only and locus-only submissions are accepted.

## Running with workers

The backend is a **control plane only** — it queues jobs and hands them to
external workers (see `worker/README.md`). It never runs annotation jobs
in-process.

Persistent laptop workers and scheduler-launched HPC workers can pull from the
same backend queue. The backend does not push jobs to either fleet:

```bash
# laptop
BACKEND_URL=https://api.example WORKER_API_TOKEN=… python -m worker serve

# HPC scrontab
*/5 * * * * /opt/gene-autoannotator/deploy/scripts/dispatcher-once.sh >> /opt/gene-autoannotator/dispatcher.log 2>&1
```

Environment variables:

- `WORKER_API_TOKEN`: shared secret required on the worker endpoints
  (`/workers/*`, `/jobs/{id}/progress|complete|fail`). Workers must send it as
  `Authorization: Bearer <token>`. **If unset, the worker endpoints are
  unauthenticated.**
- `WORKER_CAPACITY_REQUIRED` (default on for `backend.api:app`): reject job
  submission with 503 while no worker is connected with a free slot. Set it to
  `0` for an HPC-primary deploy where workers only exist after the dispatcher
  reacts to a queued job.
- `LEASE_SECONDS` (default `21600`, 6 hours): how long a claimed job's lease is valid
  before the reaper may requeue it. Progress reports and worker heartbeats renew
  the lease, so a live worker keeps its job past the lease window; a worker that
  dies (for example a killed Slurm allocation) releases its job after it.
- `MAX_ATTEMPTS` (default `3`): maximum number of times a job is retried before it
  is marked failed.
- `WORKER_OFFLINE_SECONDS` (default `60`): a worker with no heartbeat within this
  window is reported as offline in `/health` and `/workers` (both admin-only).
- `REQUIRED_WORKER_VERSION` (optional): if set, returned to workers on heartbeat
  so out-of-date agents can be told to update.
- `BACKEND_PUBLIC_URL` / `APP_VERSION`: surfaced by `GET /backend-info`
  (admin-only) so operators can see the backend URL and version.
- `TERMS_VERSION` (default `draft-2026-09`): `POST /auth/signup` requires
  `"accept_terms": true` (422 otherwise), and a new account is created with
  this value in `terms_version` and the creation time in `terms_accepted_at`.
  When you change it, bump the `TERMS_VERSION` constant in
  `frontend/lib/legal.js` in the same change (the legal pages display that
  constant). Accounts created before consent was required keep null values
  (shown read-only in `GET /admin/users`) until they verify a code from a new
  signup request, which records the current version; they are not otherwise
  asked to re-consent.
- Admin alerts: every `ALERT_CHECK_SECONDS` (default `300`, capped at `86400`;
  `0` disables) the
  backend emails all active admins through `EMAIL_BACKEND` (`console` logs
  them) when a rule trips. Each alert repeats at most every 6 hours while it
  persists. A threshold of `0` disables that rule; invalid values fall back to
  the default with a logged warning.
  - `ALERT_QUEUE_DEPTH` (default `50`): jobs queued.
  - `ALERT_NO_WORKER_MINUTES` (default `15`): jobs queued with no online ready
    or provisioning worker (draining workers don't count) for this long.
  - `ALERT_FAILURE_RATE` (default `0.5`): failed / (completed + failed) over
    the last hour, once at least 5 jobs have finished.
- Control-plane backups (see [Backups and restore](#backups-and-restore)):
  `BACKUP_INTERVAL_SECONDS` (default `21600`, 6 hours, capped at 7 days; `0`
  disables) and `BACKUP_KEEP` (default `28`, minimum `1`). Backups only run
  when `MONGO_URI` is set.
- `JOB_RETENTION_DAYS` (default `0`, keep forever; capped at `36500`): once a
  day, delete completed, failed, and cancelled jobs that finished more than this
  many days ago, plus batches older than that with no jobs left. Queued and
  running jobs are never purged. Only the SQLite rows are removed: result files
  on disk referenced by a job's `output_path` and annotation history in MongoDB
  are left in place. Each purge that deletes something records a `jobs_purged`
  audit event (no actor, `"source": "system"`) with the counts.
- `AUDIT_RETENTION_DAYS` (default `365`; `0` keeps the audit log forever;
  capped at `36500`): the same daily run deletes audit events older than this.
  It also always deletes sessions that expired, and sign-in codes used or
  expired, more than a day ago, and rate-limit rows older than two days. When
  anything is deleted it records one `personal_data_pruned` audit event with
  the counts. The daily run starts about a minute after the backend and does
  not need MongoDB.

Deleting an account (`DELETE /admin/users/{id}`) removes the user, their
sessions, sign-in codes, and email-keyed rate-limit rows, cancels their queued
and running jobs, and sets `submitted_by_user_id` to NULL on their jobs and
batches (the rows stay for the shared history and the retention purge). The
`user_delete` audit event stores a masked email (`s***@gmail.com`), never the
full address. See [deploy/docs/data-inventory.md](../deploy/docs/data-inventory.md).

Invalid backup and retention values fall back to the default with a logged
warning.

Start the backend:

```bash
WORKER_API_TOKEN=dev-token uvicorn backend.api:app --host 0.0.0.0 --port 8000
```

Job submission returns **503** when no workers are connected with available
slots, unless `WORKER_CAPACITY_REQUIRED=0`.

Set `SUBMISSIONS_PAUSED=1` to stop new job and batch submissions from
non-admins (restart the backend after changing it; with Compose, recreate the
container).
They get **503** `{"detail": "New submissions are paused. Please try again
later.", "code": "paused"}`, and `GET /jobs/queue-status` reports
`"accepting": false, "paused": true`. Admins can still submit; queued and
running jobs are unaffected.

## Endpoint Summary

- `GET /healthz`: public liveness probe; returns `{"status": "ok"}` only.
- `GET /health` (admin-only): API, SQLite job store, Mongo annotation store,
  local profile store, queue, and process resource health.
- `GET /profiles`: lists local organism profiles (JSON files under
  `PROFILES_DIR`, default `data/profiles`).
- `POST /profiles`: creates a local profile file.
- `GET /profiles/{profile_id}`: returns a local profile.
- `PUT /profiles/{profile_id}`: updates a local profile.
- `DELETE /profiles/{profile_id}`: deletes a local profile.
- `POST /validate`: runs target preflight for a profile or ad hoc organism plus
  name, locus, or both. The response includes the resolved profile, submitted and
  resolved identifiers, primary identifier, and warnings such as missing locus,
  missing gene name, locus schema mismatch, or ad hoc profile usage.
- `GET /jobs`: lists shared jobs with queue positions (non-admins see only
  their own). Admins also get `submitted_by_user_id` and `submitted_by_email`.
- `DELETE /jobs/history`: clears completed and failed job history while leaving
  queued and running jobs untouched.
- `POST /jobs`: runs the same target preflight, stores it as
  `request.target_preflight`, creates an annotation job, and returns a `job_id`.
  Jobs are persisted in SQLite and executed sequentially; only one job runs at a
  time.
- `GET /jobs/{job_id}`: returns job status and metadata.
- `GET /jobs/{job_id}/result`: returns completed annotation JSON.
- `GET /annotations/search?query=...`: searches current generated annotations through FastAPI; the Next.js UI uses its own direct MongoDB read route.
- `GET /annotations/{annotation_id}`: returns the current stored annotation through FastAPI; the Next.js UI uses its own direct MongoDB read route.
- `GET /annotations/{annotation_id}/versions`: returns older stored versions through FastAPI; the Next.js UI uses its own direct MongoDB read route.

## Batch Job Submission

Batch endpoints queue many per-gene annotation jobs under a shared batch record.
They use the same profile/organism options and target resolution as single-job
`POST /jobs`, but accept a list of genes instead of one `name`/`locus` pair.

### Batch endpoints

- `POST /batches/validate`: parses and resolves entries; returns a per-row
  preview (`ready`, `ambiguous`, `invalid`, `duplicate_skipped`) and summary
  counts. No database writes.
- `POST /batches`: creates a batch record and child jobs for `ready` entries
  only; returns `batch_id`, `job_ids`, `skipped` rows, and summary counts.
  Ambiguous or invalid rows are reported but not queued. Returns 422 if no rows
  are ready.
- `GET /batches/{batch_id}`: returns batch metadata, input summary, and
  aggregate queue counts (queued, running, completed, failed).
- `GET /jobs?batch_id={batch_id}`: lists child jobs for a batch (same response
  shape as `GET /jobs`).

Batch requests require `profile` or `organism` (same rules as single-job
submissions). Send parsed entries in `entries` and/or paste/upload content in
`raw_text`.

### Accepted input formats

Batch input is plain structured text only — not Excel or other binary formats.

**Accepted file extensions:** `.txt`, `.csv`, `.tsv`  
**Not accepted:** `.xlsx`, `.xls`

If a user has an Excel gene list, they should copy one column into the
textarea or save as CSV (one column, or two columns `locus,name`).

**Format A — one identifier per line (primary).** Each line is one locus or gene
name; resolution decides which. Blank lines and `#` comments are ignored;
surrounding quotes are stripped.

```
Rv0001
dnaA
rpoB
```

**Format B — delimited single-column list.** Same identifiers as Format A,
but tokens may also be separated by comma, semicolon, or tab on one or more
lines:

```
Rv0001, Rv0002, dnaA
```

**Format C — two-column locus + name (optional, strict).** Exactly two columns;
three or more columns reject the entire file. Column 1 is locus (optional),
column 2 is gene name (optional); at least one must be non-empty per row. The
first row is treated as a header only if every cell matches known header tokens
(`locus`, `gene`, `name`, `id`, case-insensitive).

```
locus,name
Rv0001,dnaA
Rv0002,
,dnaA
```

After parsing, a single token (`Rv0001` or `dnaA`) goes through hybrid
resolution; an explicit `locus,name` pair is treated like a single-job submission
with both identifiers supplied.

## Docker Compose

For internet-facing deployments use the production stack instead
(`deploy/compose/docker-compose.prod.yml`: prebuilt images behind Caddy, split
`backend.env`/`frontend.env`, staging mode, data migration from this stack,
update cron); see [`deploy/README.md`](../deploy/README.md). This section
covers the LAN/dev stack.

From the project root, copy `backend.env.example` to `.env`, then start the
backend API and Next.js frontend:

```bash
cp backend.env.example .env
docker compose -f deploy/compose/docker-compose.backend.yml up --build
```

The `backend` service listens on port 8000 and the frontend on port 3000. Job
queue state is persisted in a Docker volume mounted at `/state/backend`
(SQLite). Set `MONGO_URI` in `.env` for annotation history; organism profiles
are stored locally under `data/profiles` (mount or set `PROFILES_DIR` if
needed). The frontend proxy uses `BACKEND_API_BASE_URL=http://backend:8000`
inside the compose network.

Both containers read their runtime settings only from the root `.env` (the
frontend image no longer contains `frontend/.env.local`; `.dockerignore` keeps
every `.env*` file out of the build). Before each build or redeploy, check it:

```bash
deploy/scripts/preflight-env.sh            # or: deploy/scripts/preflight-env.sh /path/to/.env
docker compose -f deploy/compose/docker-compose.backend.yml build
docker compose -f deploy/compose/docker-compose.backend.yml up -d
```

The preflight prints `OK NAME` or `MISSING NAME` (never values) for
`MONGO_URI` (or `MONGODB_URI`; the frontend's annotation routes need it too),
`WORKER_API_TOKEN`, `REQUIRE_WORKER_API_TOKEN`, `SESSION_COOKIE_SECURE`,
`EMAIL_BACKEND`, and, when `EMAIL_BACKEND=resend`, `RESEND_API_KEY` and
`EMAIL_FROM`. It exits non-zero if any is missing, empty, or still a
`CHANGE_ME` placeholder; fix `.env` before building. For the production
stack's split files use `--role backend` / `--role frontend` (see
`deploy/README.md`).

The backend image installs only `requirements-backend.txt`, pinned by
`deploy/docker/constraints-backend.txt` (no torch, CUDA,
transformers, or spaCy; the annotation pipeline runs on workers). The server
runs as the unprivileged user `app` (uid/gid 10001). The container starts as
root only long enough for its entrypoint to chown the `/state/backend` and
`/app/data/profiles` volumes to 10001:10001, so volumes created by older,
root-run images keep working after `up -d --build` with no manual migration.
If you run the image as a non-root user (`--user`), the entrypoint skips the
chown and exits with an error naming any data dir it cannot write; fix it once
with `chown -R 10001:10001` on the volume. The frontend image is Next.js
`output: "standalone"` and runs as the image's `node` user.

The backend runs uvicorn with `--no-proxy-headers`, so `request.client` is
always the TCP peer. Client IPs for rate limits come from `X-Forwarded-For`
only when `TRUST_FORWARDED_FOR=1` (see `backend/client_ip.py`); set it only when
every request reaches the backend through a proxy that overwrites that header
and port 8000 is not reachable from outside.

`docker compose exec` bypasses the entrypoint and runs as root, so pass
`-u app` (as in the commands below) or files it creates in the volumes stay
root-owned until the next container start. `docker compose run` goes through
the entrypoint and needs no flag.

## Account management CLI

`python -m backend.manage` changes accounts directly in SQLite. It is the
lockout-recovery path: the bootstrap admin is only auto-promoted once, and
unlike the admin API the CLI does not block removing the last admin (it prints
a warning instead). Every change is written to the audit log with no actor and
`"source": "cli"`.

```bash
python -m backend.manage list-users [--query alice] [--limit 200]
python -m backend.manage set-role EMAIL {user,admin}
python -m backend.manage set-status EMAIL {active,suspended}  # suspending also revokes sessions and cancels jobs
python -m backend.manage revoke-sessions EMAIL
python -m backend.manage cancel-jobs EMAIL  # cancel queued + running jobs, keep the account
```

Suspending a user (here or with `PATCH /admin/users/{id}`) cancels their queued
and running jobs; running jobs stop on the worker's next progress report. The
count is recorded as `cancelled_jobs` in the `status_change` audit event.
`cancel-jobs` records a `jobs_cancelled` event.

Run it from the repo root locally; it uses the same default database as the API
(`backend/jobs.sqlite3`, relative to the working directory). Pass `--db PATH`
to target another file. With Docker Compose, run it inside the backend
container so it sees the `/state/backend` volume:

```bash
docker compose -f deploy/compose/docker-compose.backend.yml exec -u app backend \
  python -m backend.manage set-role solavolantes@gmail.com user
```

Emails match case-insensitively. Exit codes: `0` success, `1` unknown email,
invalid role/status, or missing database, `2` usage error.

## Backups and restore

The backend's control plane is one SQLite file (`backend/jobs.sqlite3`: users,
sessions, sign-in codes, jobs, batches, workers, audit log, rate limits) plus
the profiles directory (`PROFILES_DIR`). With `MONGO_URI` set, the backend
uploads a snapshot of both every `BACKUP_INTERVAL_SECONDS` (first one about a
minute after startup) to the GridFS bucket `control_plane_backups` in the same
MongoDB database as annotation history, and deletes all but the newest
`BACKUP_KEEP`. A failed backup is logged and retried at the next interval; it
never stops the backend. Without `MONGO_URI` backups are off (logged at
startup).

A snapshot is a `.tar.gz` holding `control-plane.sqlite3` (a consistent copy
made with SQLite's online backup API, safe while the backend is writing) and
`profiles/<file>` for each top-level file in the profiles directory. Its
metadata is only `created_at`, `app_version`, and `db_bytes`. **Backups are as
sensitive as the database**: they contain account emails, session and sign-in
code hashes, and the audit log, so protect the MongoDB credentials
accordingly. Budget storage for `BACKUP_KEEP` snapshots.

```bash
python -m backend.manage backup                     # upload one now; prints id and size
python -m backend.manage list-backups               # ID, CREATED_AT, SIZE (bytes), newest first
python -m backend.manage restore [--id ID|latest] [--force]
```

`backup` and `restore` use `--db` and `--profiles-dir` (default
`$PROFILES_DIR`, else `data/profiles`) like the API. Both are recorded in the
audit log (`backup_created`, `backup_restored`; `restore` writes into the
restored database).

**Restore requires the backend to be stopped**: a running backend keeps
writing to the old database file and can overwrite restored state. Without
`--force`, `restore` refuses if the database (or a leftover `-wal`/`-shm`/
`-journal` file) exists or if the profiles directory contains any files. With
`--force` nothing is deleted: the database and its sidecar files are renamed
to `jobs.sqlite3.pre-restore-<timestamp>` (with `-wal`/`-shm` appended, so the
moved copy still opens with its WAL), and the existing profile files are moved
into `<profiles dir>/.pre-restore-<timestamp>/` (inside the directory because
it is a volume mount in Compose). The profiles directory then holds exactly the
snapshot's files. The archive is validated before anything is moved: only a
regular `control-plane.sqlite3` and regular `profiles/<name>` files are
accepted (no absolute paths, `..`, links, or nested directories), and the
database must pass `PRAGMA quick_check`. The new database is swapped in with an
atomic rename.

With Docker Compose, restore in a one-off container that mounts the same
volumes, then start the backend again:

```bash
docker compose -f deploy/compose/docker-compose.backend.yml stop backend
docker compose -f deploy/compose/docker-compose.backend.yml run --rm backend \
  python -m backend.manage list-backups
docker compose -f deploy/compose/docker-compose.backend.yml run --rm backend \
  python -m backend.manage restore --id latest --force
docker compose -f deploy/compose/docker-compose.backend.yml start backend
```

Delete the `*.pre-restore-*` copies once the restored backend looks right.
