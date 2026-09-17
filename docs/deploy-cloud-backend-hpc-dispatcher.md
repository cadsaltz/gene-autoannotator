# Deploying the Cloud Backend and SCRI Dispatcher

This deployment keeps one public control plane and one durable job queue:

- A cloud host runs the Next.js frontend and FastAPI backend.
- The backend owns the SQLite queue and local organism profiles.
- MongoDB stores completed annotation history for both the backend and frontend.
- SCRI compute nodes and optional laptops initiate outbound HTTPS connections to
  the backend and claim work. The backend never connects to compute hosts.
- The SCRI login-node dispatcher only peeks at queue depth and submits Slurm
  allocations. A Slurm worker performs the atomic claim after it starts.

The canonical Python package and Compose service are named `backend`.

## 1. Cloud frontend and backend

### Host and network

Provision a Linux host with Docker Engine and the Compose plugin. Give it durable
storage for Docker volumes and terminate TLS with the cloud load balancer or a
reverse proxy:

- Route the public application hostname to frontend port `3000`.
- Route a public backend hostname to backend port `8000`; SCRI and laptop
  workers must be able to reach it over HTTPS.
- Do not publish MongoDB to the internet.

The frontend uses same-origin `/api/backend` routes and reaches FastAPI over the
Compose network. Workers use the public backend URL directly.

### Environment

From the repository root, create `.env` (it is gitignored):

```dotenv
WORKER_API_TOKEN=replace-with-a-long-random-token
BACKEND_PUBLIC_URL=https://api.example.org
MONGO_URI=mongodb+srv://USER:PASSWORD@HOST/gene_autoannotator
PROFILES_DIR=/app/data/profiles
WORKER_CAPACITY_REQUIRED=0
LEASE_SECONDS=21600
MAX_ATTEMPTS=3
WORKER_OFFLINE_SECONDS=60
CORS_ORIGINS=https://annotations.example.org
```

Generate the worker token with `deploy/scripts/generate-worker-token.sh`. Use
the same token on the backend, dispatcher, and every worker, but keep it out of
shell history, source control, and Slurm logs.

`WORKER_API_TOKEN` protects worker registration, deregistration, claim,
progress, completion, failure, drain, and `GET /jobs/queue-summary` when
configured. It is not end-user account authentication.

### Submission capacity gate (required reading for HPC-only deploys)

`backend.api:app` rejects `POST /jobs` and `POST /batches` with 503 while no
worker is connected with a free slot. That default assumes a warm worker, and it
deadlocks an HPC-only deploy: the dispatcher only submits Slurm allocations once
jobs are queued, so nothing can ever be queued if submission requires a worker
that does not exist yet.

Choose one:

- **HPC-only (recommended for this deployment):** set
  `WORKER_CAPACITY_REQUIRED=0`, as in the `.env` above. Submissions are always
  accepted and wait in the queue until the next dispatcher pass launches a
  worker.
- **Warm-worker deploys:** keep `WORKER_CAPACITY_REQUIRED=1` and run at least
  one always-on laptop worker (section 4). Users then get an immediate 503 when
  no capacity is connected, instead of a job that waits for capacity.

### Lease duration and Slurm walltime

`LEASE_SECONDS` is how long a claimed job stays assigned to a worker that stops
reporting. Live workers renew the lease on every progress report and heartbeat,
so a long job on a healthy worker is never requeued. A worker that dies — a
killed or preempted Slurm allocation, a node failure — only releases its job
after the lease expires, so a very long lease strands the job.

Set `LEASE_SECONDS` slightly above the longest expected gap in worker reporting,
not above total walltime: 4–6 hours (`14400`–`21600`, the default) suits the
`--time=48:00:00` sample allocation. Requeued jobs are retried up to
`MAX_ATTEMPTS`.

### Start

```bash
docker compose -f deploy/compose/docker-compose.backend.yml up -d --build
docker compose -f deploy/compose/docker-compose.backend.yml ps
curl -fsS https://api.example.org/health
```

Compose starts the `frontend` and `backend` services. The frontend receives
`BACKEND_API_BASE_URL=http://backend:8000`; both services receive `.env`.
The backend runs from `/app` with `/state` as its working directory. Its
relative SQLite path therefore resolves to
`/state/backend/jobs.sqlite3`, persisted in the `backend-data` volume,
without mounting over the packaged Python source. Profiles are persisted in
`profiles-data`. Back up both volumes before host replacement or rollback.

Use a single active backend instance with the current SQLite queue. Running
multiple backend replicas against independent volumes would create multiple
queues; sharing SQLite over a network filesystem is not a supported scaling
path.

## 2. MongoDB

Use a managed MongoDB deployment or a separately administered private MongoDB
service. Put the same `MONGO_URI` in the cloud `.env` so FastAPI can write
completed annotations and Next.js server routes can search and review them.

MongoDB is not the queue and does not store organism profiles. If it is
unavailable, the API can remain online and jobs can run, but completed
annotations cannot be persisted to annotation history and frontend
search/review is unavailable. Confirm the `annotation_store` result in
`GET /health` before accepting production work.

## 3. SCRI installation

The repository must be on a path visible from the SCRI login node and Slurm
compute nodes. Compute nodes need outbound HTTPS access to the public backend
and internet access required by the annotation pipeline. The login node needs a
Python environment that can run `python -m dispatcher once` (peek + `sbatch`
only). GPU annotation runs inside an Apptainer/Singularity image built from
`deploy/docker/Dockerfile.worker` — the same packaging shape as the proven SCRI
bench job, but with `worker run` (bounded queue drain via `WORKER_RUN_MAX_JOBS`).

Build or copy a worker SIF onto the shared path (example name below). Copy
`dispatcher.env.example` → `dispatcher.env` and
`deploy/docker/worker.run.env.example` → `worker.run.env`; fill in
`BACKEND_URL` / `WORKER_API_TOKEN` and fleet/concurrency knobs.

The sample `deploy/slurm/worker-run.sbatch` already uses SCRI-style resources
(`gpu-core`, `ma_lab_main`, 32 CPU, 480g, 1 GPU). Adjust only if your account
or partition differs. Keep the job name `gene-autoannotator-run`; the
dispatcher uses it to count this user's in-flight Slurm jobs.

Create private env files on the shared repository path (see `dispatcher.env.example`):

```dotenv
BACKEND_URL=https://api.example.org
WORKER_API_TOKEN=replace-with-the-cloud-worker-token
DISPATCHER_SBATCH_SCRIPT=/shared/gene-autoannotator/deploy/slurm/worker-run.sbatch

# Max jobs one Slurm allocation drains (exported as WORKER_RUN_MAX_JOBS):
DISPATCHER_MAX_JOBS_PER_WORKER=500

# Backward compat only — effective Slurm inflight cap is always 1:
DISPATCHER_MAX_INFLIGHT=1

# Inherited by sbatch (--export=ALL) for the Apptainer child:
WORKER_IMAGE=/shared/gene-autoannotator/gene-autoannotator-worker_0.2.sif
WORKER_RUN_ENV_FILE=/shared/gene-autoannotator/worker.run.env
WORKER_MODELS_DIR=/shared/gene-autoannotator/models
WORKER_CACHE_DIR=/shared/gene-autoannotator/.cache/worker-run
WORKER_OUTPUT_DIR=/shared/gene-autoannotator/gen_json
```

In `worker.run.env`, set **`OLLAMA_FLEET_SERVERS`** to the GPU count on the
allocated node (must match `#SBATCH --gpus` in `worker-run.sbatch`) and tune
**`WORKER_MAX_SLOTS`** / **`OLLAMA_FLEET_PARALLEL`** for in-allocation
concurrency — not multiple Slurm jobs.

```bash
chmod 600 /shared/gene-autoannotator/dispatcher.env
chmod 600 /shared/gene-autoannotator/worker.run.env
chmod +x /shared/gene-autoannotator/deploy/scripts/dispatcher-once.sh
chmod +x /shared/gene-autoannotator/deploy/scripts/run-worker-run.sh
```

Run one manual dispatcher pass from the login node:

```bash
/shared/gene-autoannotator/deploy/scripts/dispatcher-once.sh
squeue --user "$USER" --name gene-autoannotator-run
```

`dispatcher-once.sh` sources `dispatcher.env` (or `DISPATCHER_ENV_FILE`) and runs
`python -m dispatcher once`. The dispatcher reads `GET /jobs/queue-summary`,
counts matching Slurm jobs, and applies the **single-worker rule**: submit
**at most one** new allocation when `queued > 0` and no
`gene-autoannotator-run` job is already pending or running for this user.
Otherwise it launches zero on this pass.

Each allocation runs `deploy/scripts/run-worker-run.sh`, which Apptainer-execs
`worker-run-entrypoint.sh` → `python -m worker run`. The dispatcher exports
`WORKER_RUN_MAX_JOBS` from `DISPATCHER_MAX_JOBS_PER_WORKER`; the worker
registers once, provisions Ollama, and drains up to that many jobs (using
`WORKER_MAX_SLOTS` concurrent subprocesses) before deregistering and exiting.
An empty queue at claim time is a successful no-op. Queue peeking never
reserves work; the worker claim is the only `queued` → `running` transition, so
SCRI and laptop workers can race safely for the same queue.

While jobs run, the allocation heartbeats to the backend, which keeps each
job's lease fresh and keeps the worker visible as online. On exit the
allocation deregisters itself, so a finished Slurm job disappears from
`GET /workers` instead of lingering as a stale entry. If the queue still has
work after the chunk cap or drain completes, the **next** dispatcher tick may
start another single allocation.

### Install the SCRI scrontab entry

Edit the SCRI scrontab with the site's `scrontab` command and add a periodic
login-node invocation (no nested Slurm parent — the tick runs on the login
node and only `sbatch`s GPU children):

```cron
*/5 * * * * /shared/gene-autoannotator/deploy/scripts/dispatcher-once.sh >> /shared/gene-autoannotator/dispatcher.log 2>&1
```

Confirm the entry using the SCRI-supported scrontab listing command, then watch
`dispatcher.log` and `squeue`. Keep the interval longer than a normal dispatcher
pass so invocations do not overlap. The dispatcher must run on a host with
`squeue` and `sbatch`; do not run it in the cloud Compose stack.

## 4. Optional laptop capacity

A spare laptop can continuously pull from the same cloud queue:

```bash
BACKEND_URL=https://api.example.org \
WORKER_API_TOKEN=replace-with-the-cloud-worker-token \
python -m worker serve
```

Persist fleet settings in `worker.env` and use the install/systemd guidance in
`worker/README.md` for an unattended worker. No inbound laptop firewall rule is
required; the laptop initiates backend requests.

## 5. Verification

Before exposing the service to users:

1. `GET /health` reports the queue, profile store, and Mongo annotation store as
   healthy.
2. The frontend can submit a job and poll it through the backend proxy.
3. With no Slurm run inflight, a job can be submitted and stays `queued`, and
   the next dispatcher pass submits **at most one** `gene-autoannotator-run`.
4. A Slurm allocation registers, drains up to `DISPATCHER_MAX_JOBS_PER_WORKER`
   jobs (or until the queue empties), reports progress, deregisters, and exits.
5. An optional laptop worker can claim from the same queue without duplicate
   execution, including a one-slot worker while a larger idle worker is
   registered.
6. Queue and profile volumes, MongoDB, dispatcher token file, and TLS
   certificates have an owner and backup policy.

## Authentication status

Task 9 account authentication is pending lead confirmation. Do not treat the
worker bearer token as user authentication: submission, profile, and other
public application routes do not yet have the planned account gate. Until the
lead confirms and that task is implemented, restrict public access at the load
balancer/reverse proxy or deploy only to explicitly trusted users. Do not invent
an application auth scheme in deployment configuration.

## Rollback

The pre-redesign rollback tag is:

```text
pre-cloud-hpc-redesign-2026-08-24
```

Stop the SCRI scrontab entry first so it cannot submit new one-shot workers.
Allow or drain active workers, back up the SQLite/profile volumes and MongoDB,
then deploy an image built from the rollback tag. For a source checkout:

```bash
git switch --detach pre-cloud-hpc-redesign-2026-08-24
docker compose -f deploy/compose/docker-compose.backend.yml up -d --build
```

The tag predates the cloud/HPC redesign. Its runtime and environment contract
may not understand dispatcher-launched workers or newer queue records, so
validate the rollback against copies of production data before an emergency.
