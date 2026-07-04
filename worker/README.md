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

**Terminal 1 — coordinator with the embedded worker OFF** (control-plane only):

```bash
AUTOANNOTATOR_EMBEDDED_WORKER=false WORKER_API_TOKEN=dev-token \
uvicorn coordinator.api:app --host 0.0.0.0 --port 8000
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
