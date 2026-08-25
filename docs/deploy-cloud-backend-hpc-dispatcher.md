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
`coordinator.api` remains available temporarily as a compatibility entrypoint.

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
LEASE_SECONDS=31536000
MAX_ATTEMPTS=3
WORKER_OFFLINE_SECONDS=60
CORS_ORIGINS=https://annotations.example.org
```

Generate the worker token with `deploy/scripts/generate-worker-token.sh`. Use
the same token on the backend, dispatcher, and every worker, but keep it out of
shell history, source control, and Slurm logs.

`WORKER_API_TOKEN` protects worker registration, claim, progress, completion,
failure, and drain endpoints when configured. It is not end-user account
authentication. `GET /jobs/queue-summary` is currently a public read-only
endpoint; the dispatcher still sends the bearer token with its request.

### Start

The current Compose filename retains the old role name:

```bash
docker compose -f deploy/compose/docker-compose.coordinator.yml up -d --build
docker compose -f deploy/compose/docker-compose.coordinator.yml ps
curl -fsS https://api.example.org/health
```

Compose starts the `frontend` and `backend` services. The frontend receives
`BACKEND_API_BASE_URL=http://backend:8000`; both services receive `.env`.
The backend runs from `/app` with `/state` as its working directory. Its
relative SQLite path therefore resolves to
`/state/coordinator/jobs.sqlite3`, persisted in the `coordinator-data` volume,
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

The repository and virtual environment must be on a path visible from the SCRI
login node and Slurm compute nodes. Compute nodes need outbound HTTPS access to
the public backend and internet access required by the annotation pipeline.
Install the project dependencies and Ollama as described in `worker/README.md`.

Copy and customize `deploy/slurm/worker-run.sbatch`:

1. Replace `#SBATCH --partition=REPLACE_ME`.
2. Adjust GPU, CPU, memory, wall time, account, and module directives for SCRI.
3. Ensure `python` resolves to the project virtual environment on compute nodes,
   or change the final command to its absolute path.
4. Keep the job name `gene-autoannotator-run`; the dispatcher uses it to count
   this user's in-flight Slurm jobs.

Create a private dispatcher environment file on the shared repository path:

```dotenv
BACKEND_URL=https://api.example.org
WORKER_API_TOKEN=replace-with-the-cloud-worker-token
DISPATCHER_MAX_INFLIGHT=4
DISPATCHER_SBATCH_SCRIPT=/shared/gene-autoannotator/deploy/slurm/worker-run.sbatch

# Worker/model settings inherited by sbatch:
AUTOANNOTATION_MODEL_MODE=performance
WORKER_MAX_SLOTS=1
OLLAMA_FLEET_SERVERS=1
OLLAMA_FLEET_PARALLEL=1
```

```bash
chmod 600 /shared/gene-autoannotator/dispatcher.env
```

Run one manual dispatcher pass from the login node:

```bash
cd /shared/gene-autoannotator
set -a
. ./dispatcher.env
set +a
.venv/bin/python -m dispatcher once
squeue --user "$USER" --name gene-autoannotator-run
```

The dispatcher reads `GET /jobs/queue-summary`, counts matching Slurm jobs, and
submits at most:

```text
min(queued jobs, DISPATCHER_MAX_INFLIGHT - matching Slurm jobs)
```

Each allocation runs `python -m worker run --claim-one`. An empty queue is a
successful no-op. Queue peeking never reserves work; the worker claim is the
only `queued` to `running` transition, so SCRI and laptop workers can race
safely for the same queue.

### Install the SCRI scrontab entry

Edit the SCRI scrontab with the site's `scrontab` command and add a periodic
login-node invocation:

```cron
*/5 * * * * cd /shared/gene-autoannotator && set -a && . ./dispatcher.env && set +a && .venv/bin/python -m dispatcher once >> dispatcher.log 2>&1
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
3. A dispatcher pass submits no more than `DISPATCHER_MAX_INFLIGHT`.
4. A Slurm allocation registers, claims one job, reports progress, completes,
   and exits.
5. An optional laptop worker can claim from the same queue without duplicate
   execution.
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
docker compose -f deploy/compose/docker-compose.coordinator.yml up -d --build
```

The tag predates the cloud/HPC redesign. Its runtime and environment contract
may not understand dispatcher-launched workers or newer queue records, so
validate the rollback against copies of production data before an emergency.
