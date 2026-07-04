# Gene Autoannotator Worker

The worker is a stateless REST agent that runs the annotation pipeline on a
remote machine. It registers with the coordinator, polls for jobs, executes the
**unchanged** `autoannotation` pipeline in-process, and reports progress,
results, and failures back to the coordinator. It stores no state of its own;
all queue and result state lives in the coordinator's SQLite database.

The main loop is `worker.agent.run()`:

1. Load config from environment (`worker/config.py`).
2. `POST /workers/register` and log `Registered worker <name> (<slots> slots)`.
3. Each iteration (`run_once`): send a heartbeat, then if a slot is free and the
   memory admission gate passes, claim a job (`POST /workers/<id>/claim`), run it
   via `worker/executor.py` (which calls `autoannotation.__main__.main(...)`),
   and report `complete` or `fail`.

## Prerequisites

- Python 3.11+.
- The repository installed with its dependencies (see the root and
  `coordinator/README.md` setup steps: `requirements.txt` + `requirements-web.txt`).
- A reachable coordinator (see `coordinator/README.md`).
- **Ollama running locally.** Real jobs run the same annotation code as the CLI, so
  the worker host needs the same local services, network access, and cache/output
  directories as the terminal command. Required LLM models are **auto-pulled on
  startup** via `worker.ollama_bootstrap.ensure_models()` (called from
  `worker.agent.run()` before registration).

### Ollama models

The set of required models is derived from `autoannotation.models`
(`MODEL_SUMMARY` plus `MODEL_CONSENSUS` and `MODEL_AGGREGATION`). On startup,
`worker.agent.run()` calls `ensure_models()` to pull any missing ones via the
local Ollama client:

```python
from worker.ollama_bootstrap import ensure_models
ensure_models()  # pulls any missing models via the local Ollama client
```

Until model provisioning finishes, the worker heartbeats with `state="provisioning"`
and does not claim jobs. After all required models are present, heartbeats use
`state="ready"` and the worker may claim work.

## Environment variables

From `worker/config.py`:

| Variable | Required | Default | Purpose |
| --- | --- | --- | --- |
| `COORDINATOR_URL` | **yes** | — | Base URL of the coordinator, e.g. `http://coord-host:8000`. A trailing slash is stripped. |
| `WORKER_API_TOKEN` | recommended | `""` | Shared secret sent as `Authorization: Bearer <token>`. Must match the coordinator's `WORKER_API_TOKEN`. If the coordinator has a token set and this is empty/wrong, worker requests are rejected with 401. |
| `WORKER_NAME` | no | hostname | Human-readable name reported at registration. |
| `ANNOTATION_MEMORY_BUDGET_GB` | effectively yes | `0` | Memory (GB) this worker dedicates to annotation. Drives the slot count. **If it is too low the worker gets 0 slots and will register but never claim a job** — set it above one job's requirement. |
| `APP_VERSION` | no | `dev` | Agent version reported to the coordinator (used with the coordinator's `REQUIRED_WORKER_VERSION` check). |
| `HEARTBEAT_SECONDS` | no | `15` | Heartbeat interval hint stored on the config. |

Capacity tunables (from `worker/capacity.py`) control how the memory budget maps
to slots and to the per-claim admission gate:

| Variable | Default | Purpose |
| --- | --- | --- |
| `JOB_MEMORY_ESTIMATE_GB` | `20.0` | Estimated peak memory per annotation job. |
| `WORKER_MEMORY_HEADROOM_GB` | `4.0` | Memory held back from the budget for headroom. |

Slots are computed as `floor((ANNOTATION_MEMORY_BUDGET_GB - WORKER_MEMORY_HEADROOM_GB) / JOB_MEMORY_ESTIMATE_GB)`.
With the defaults, `ANNOTATION_MEMORY_BUDGET_GB=24` yields 1 slot.

## Running the worker

```bash
COORDINATOR_URL=http://<coord-host>:8000 \
WORKER_API_TOKEN=<token> \
ANNOTATION_MEMORY_BUDGET_GB=24 \
python -m worker
```

On startup you should see `Registered worker <hostname> (1 slots)`. If you see a
warning about 0 slots, raise `ANNOTATION_MEMORY_BUDGET_GB`.

## Local end-to-end smoke test (manual, needs Ollama)

This exercises the full control-plane/worker split on one machine. It requires a
running Ollama instance (missing models are pulled automatically on worker startup).

**Terminal 1 — coordinator** (control plane only):

```bash
WORKER_API_TOKEN=dev-token uvicorn coordinator.api:app --host 0.0.0.0 --port 8000
```

**Terminal 2 — the worker:**

```bash
COORDINATOR_URL=http://127.0.0.1:8000 WORKER_API_TOKEN=dev-token \
ANNOTATION_MEMORY_BUDGET_GB=24 python -m worker
```

Expect the log line `Registered worker <hostname> (1 slots)`.

**Verify the worker is connected:**

```bash
curl -s http://127.0.0.1:8000/health | python -m json.tool
```

Look for `"workers": {"connected": 1, ...}`.

**Submit a job and watch it move through the queue:**

```bash
curl -s -X POST http://127.0.0.1:8000/jobs \
  -H 'Content-Type: application/json' \
  -d '{"profile":"mtb-h37rv","locus":"Rv0001","allow_online_name_lookup":false}'
```

Then poll the queue and watch the status go `queued → running → completed`, with
`worker_id` populated once the worker claims it:

```bash
curl -s "http://127.0.0.1:8000/jobs?order=queue" | python -m json.tool
```

**Legacy regression (embedded worker path still works):** stop both processes,
then start only the coordinator with its default settings (the embedded in-process
worker defaults ON):

```bash
uvicorn coordinator.api:app --host 0.0.0.0 --port 8000
```

Submit the same job. It runs in-process, exactly as before the split, with no
external worker required.

## Deployment scripts

Scripts live under `deploy/scripts/`:

| Script | Purpose |
| --- | --- |
| `generate-worker-token.sh` | Emit a random hex token for `WORKER_API_TOKEN` (set the same value on coordinator and workers). |
| `test-coordinator-reachability.sh` | Verify LAN connectivity to the coordinator (`curl` `/health`). |
| `install-worker.sh` | Create `.venv`, install dependencies, and write `worker.env` in a repo clone. |
| `update-worker.sh` | Drain active jobs, `git pull`, and restart the worker (systemd or manual). |

Make them executable once (the install script also runs `chmod +x` on the set):

```bash
chmod +x deploy/scripts/*.sh
```

### Install a worker (dev/lab clone)

From the repository root:

```bash
deploy/scripts/install-worker.sh
```

With coordinator URL and token (non-interactive):

```bash
deploy/scripts/install-worker.sh http://192.168.1.10:8000 "$(deploy/scripts/generate-worker-token.sh)"
```

If `worker.env` already exists, bootstrap reuses saved values. Otherwise run
`python -m worker` once for interactive prompts.

### Two-machine LAN setup

**Coordinator machine**

1. Generate a shared token: `deploy/scripts/generate-worker-token.sh`
2. Configure the coordinator (`.env` or environment):

   ```bash
   WORKER_API_TOKEN=<token>
   COORDINATOR_PUBLIC_URL=http://<lan-ip>:8000
   ```

   `COORDINATOR_PUBLIC_URL` is the address workers should use — set it to the
   coordinator's LAN IP (not `127.0.0.1`). The startup banner and
   `GET /coordinator-info` echo this value.

3. Allow inbound HTTP on port 8000 (example with ufw):

   ```bash
   sudo ufw allow 8000/tcp
   ```

4. Start the coordinator bound to all interfaces:

   ```bash
   uvicorn coordinator.api:app --host 0.0.0.0 --port 8000
   ```

**Worker machine(s)**

1. Clone the repo and run `deploy/scripts/install-worker.sh` (or set `worker.env` manually).
2. Test reachability before starting the worker:

   ```bash
   deploy/scripts/test-coordinator-reachability.sh http://<lan-ip>:8000
   ```

3. Start the worker (`python -m worker` or systemd below).

Each worker needs Ollama running locally with enough RAM for its slot count.

### systemd install (production)

After running `install-worker.sh` in a clone at `/opt/gene-autoannotator`:

```bash
sudo mkdir -p /etc/gene-autoannotator
sudo cp worker.env /etc/gene-autoannotator/worker.env
sudo cp deploy/systemd/gene-autoannotator-worker.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now gene-autoannotator-worker
```

The unit file reads `/etc/gene-autoannotator/worker.env`, runs from
`/opt/gene-autoannotator`, and restarts the agent on failure.

Check status: `sudo systemctl status gene-autoannotator-worker`

### Updating a worker

Drain, pull, and restart:

```bash
deploy/scripts/update-worker.sh
# or with an explicit coordinator URL:
deploy/scripts/update-worker.sh http://192.168.1.10:8000
```

The script polls `GET /workers` until this host's worker reports
`active_jobs=0` (or times out), then runs `git pull` and restarts via systemd
when the unit is enabled.
