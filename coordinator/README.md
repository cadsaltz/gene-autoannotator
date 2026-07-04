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

Copy the coordinator environment template to the project root `.env` (loaded
automatically on startup):

```bash
cp coordinator.env.example .env
```

Edit `.env` as needed — for example set `COORDINATOR_PUBLIC_URL` to your LAN IP
and configure `WORKER_API_TOKEN` before connecting external workers.

Run the API server:

```bash
uvicorn coordinator.api:app --host 0.0.0.0 --port 8000
```

On startup the coordinator logs its listen address, suggested worker
`COORDINATOR_URL`, token status, and whether the embedded in-process worker is
enabled.

Check that it is reachable:

```bash
curl http://10.158.45.197:8000/health
```

Annotation history writes and user-saved organism profiles use MongoDB. Put your
local connection string in the project root `.env` file so completed backend jobs
and custom profiles can be saved:

```bash
MONGO_URI=mongodb://localhost:27017/gene_autoannotator
```

The API will still start if MongoDB is unavailable, but `/health` will report
backend annotation/profile storage as unavailable. Completed jobs will record an
annotation storage warning until the connection is fixed, and profile create,
update, and delete calls will return a storage-unavailable error.

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
`name` or `locus`. `profile` selects a built-in or Mongo-backed saved profile;
`organism` with optional `strain` builds an ad hoc profile for one submission.
Supplying both name and locus gives the target resolver the strongest evidence,
but name-only and locus-only submissions are accepted.

## Running with workers

The coordinator is a **control plane only** — it queues jobs and hands them to
external workers (see `worker/README.md`). It never runs annotation jobs
in-process.

Environment variables:

- `WORKER_API_TOKEN`: shared secret required on the worker endpoints
  (`/workers/*`, `/jobs/{id}/progress|complete|fail`). Workers must send it as
  `Authorization: Bearer <token>`. **If unset, the worker endpoints are
  unauthenticated.**
- `LEASE_SECONDS` (default `14400`): how long a claimed job's lease is valid
  before the reaper may requeue it.
- `MAX_ATTEMPTS` (default `3`): maximum number of times a job is retried before it
  is marked failed.
- `WORKER_OFFLINE_SECONDS` (default `60`): a worker with no heartbeat within this
  window is reported as offline in `/health` and `/workers`.
- `REQUIRED_WORKER_VERSION` (optional): if set, returned to workers on heartbeat
  so out-of-date agents can be told to update.
- `COORDINATOR_PUBLIC_URL` / `APP_VERSION`: surfaced by `GET /coordinator-info`
  so workers can discover the coordinator URL and version.

Start the coordinator:

```bash
WORKER_API_TOKEN=dev-token uvicorn coordinator.api:app --host 0.0.0.0 --port 8000
```

Job submission returns **503** when no workers are connected with available slots.

## Endpoint Summary

- `GET /health`: API, SQLite job store, Mongo annotation store, profile store,
  queue, and process resource health.
- `GET /profiles`: lists built-in and Mongo-backed user organism profiles.
- `POST /profiles`: creates a Mongo-backed user profile.
- `GET /profiles/{profile_id}`: returns a built-in or user profile.
- `PUT /profiles/{profile_id}`: updates a Mongo-backed user profile. Built-in
  profiles are read-only.
- `DELETE /profiles/{profile_id}`: deletes a Mongo-backed user profile. Built-in
  profiles are read-only.
- `POST /validate`: runs target preflight for a profile or ad hoc organism plus
  name, locus, or both. The response includes the resolved profile, submitted and
  resolved identifiers, primary identifier, and warnings such as missing locus,
  missing gene name, locus schema mismatch, or ad hoc profile usage.
- `GET /jobs`: lists shared jobs with queue positions.
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

From the project root, copy `coordinator.env.example` to `.env`, then start the
coordinator API and Next.js frontend:

```bash
cp coordinator.env.example .env
docker compose -f deploy/compose/docker-compose.coordinator.yml up --build
```

The coordinator listens on port 8000 and the frontend on port 3000. Job queue
state is persisted in a Docker volume mounted at `/app/coordinator` (SQLite).
Set `MONGO_URI` in `.env` for annotation history and profile storage; the
frontend proxy uses `COORDINATOR_API_BASE_URL=http://coordinator:8000` inside
the compose network.
