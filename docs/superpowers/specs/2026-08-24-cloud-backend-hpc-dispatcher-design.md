# Cloud Backend + HPC Dispatcher — Design Spec

**Date:** 2026-08-24  
**Status:** Draft — pending user review  
**Rollback tag:** `pre-cloud-hpc-redesign-2026-08-24` (LAN coordinator + pull workers)  
**Branch:** `redesign/cloud-backend-hpc-dispatcher`  
**Approach:** Single web architecture (option C). One public job queue. All compute pulls. HPC and spare laptops are both fleet members, not separate products.

---

## 1. Goals

1. Public readers can use the UI (paper audience) without VPN.
2. SCRI/HPC has **no inbound** exposure (no port-forward into the cluster).
3. Automate Slurm submission (scrontab + nested `sbatch`, already validated on site).
4. Preserve the portable worker and annotation pipeline; do not scrap the distributed design.
5. Support **HPC dispatcher + laptop `serve` workers on the same queue**, concurrently.
6. Keep one codebase / one protocol — config chooses which launchers are running, not a second web stack.

### Non-goals (this redesign)

- Message brokers, gRPC, Kubernetes, coordinator HA replicas.
- Rewriting `autoannotation/` science/prompts.
- Making Mongo the only status channel (Mongo remains the annotation document store).
- Boss’s “workers never talk to cloud; only a dependent poster talks” as the *core* contract (allowed later as an egress workaround that still completes into the same backend API).

---

## 2. Frozen communication contract

### 2.1 Pull-only networking

- The **backend never opens connections** to workers, dispatchers, laptops, or HPC.
- Every device that needs work or must report status **initiates outbound HTTPS** to the public backend (and outbound to Mongo/Docker/NCBI as already required).
- Implication: no port-forwarding, no “cloud calls SCRI,” no push assignment.

### 2.2 Singular queue ownership

- Exactly **one** job queue, owned and persisted by the **backend** (SQLite today; Postgres later if needed).
- There is **no** second job store on HPC.
- UI create/list/progress always reads that backend queue.
- Mongo stores annotation documents / search history — **not** the live queue.

### 2.3 Atomic claim (race safety)

- Jobs move `queued → running` only through an **atomic claim** (`BEGIN IMMEDIATE` + update, already in `JobStore.assign_job_to_worker`).
- Laptop `serve` and the HPC dispatcher **both** claim via the same API.
- If both race on one job, **exactly one** wins; the other gets empty/204 and moves on.
- The backend does **not** push or assign; it only accepts claims and records progress/complete/fail.

### 2.4 Status path

- Live job status for the UI comes from the backend (`GET /jobs`, progress fields).
- Completing work must call backend `complete` / `fail` (directly from the worker, or via a thin poster that uses the **same** endpoints).
- Writing Mongo alone is **not** sufficient for queue/UI correctness.

---

## 3. Stack naming (roles)

| Role | Name | Responsibility |
|------|------|----------------|
| UI | **Frontend** | Next.js; public; proxies API; Mongo reads for annotation search |
| Control plane | **Backend** (today’s `coordinator/` package, rename over time) | Accounts (new), enqueue, persist queue, worker registry, claim/progress/complete/fail, profiles/validate |
| HPC launcher | **Dispatcher** | Periodic (scrontab) process on SCRI: poll/claim capacity, `sbatch` one-shot workers, exit |
| Compute | **Worker** | Runs `autoannotation`; three modes below |
| Science | **autoannotation** | Unchanged pipeline library |

**Rename guidance:** Prefer gradual rename (`coordinator` → `backend` in package path, env vars, docs, UI copy). Keep temporary aliases (`COORDINATOR_URL` → `BACKEND_URL` with fallback) so laptop installs do not break mid-migration.

The HPC piece is **not** a second coordinator. Calling it “coordinator” in conversation is fine; in code/docs it is the **dispatcher**.

---

## 4. Topology

```
Public internet
  Browser → Frontend → Backend (queue + worker API + accounts)
                              ↑
              outbound HTTPS only (claim / heartbeat / progress / complete)
                              │
         ┌────────────────────┴────────────────────┐
         ▼                                         ▼
  laptop `worker serve`                    HPC Dispatcher (scrontab)
  (continuous pull)                             │
                                         sbatch per claimed job
                                                ▼
                                       `worker run` (one-shot)
                                       → complete/fail to Backend
                                       → Mongo write via backend path
```

Starter production: cloud Frontend + Backend; SCRI scrontab Dispatcher; optional N laptop serves pointing at the same `BACKEND_URL`.

---

## 5. Worker modes (three)

| Mode | Command (proposed) | Who starts it | Queue? | Lifetime |
|------|--------------------|---------------|--------|----------|
| **serve** | `python -m worker serve` | Admin on spare laptop / always-on box | Claims from **backend** continuously | Until drained / stopped |
| **run** | `python -m worker run` | Dispatcher via Slurm (`sbatch`) | Does **not** re-claim; executes job(s) already claimed and materialized for this allocation | Starts → annotate → complete/fail → **exit** |
| **bench** | `python -m worker bench` | Human / CI / HPC bench scripts | Local JSONL only; **no** backend | Batch → report → exit |

### 5.1 Why serve also pulls from the backend

Yes. Serve drains the **same** public queue as the dispatcher. That keeps:

- Zero inbound to SCRI or laptops.
- One race-safe claim API.
- Ability to run dispatcher + laptops together without a special “laptop architecture.”

### 5.2 Dispatcher vs `worker run`

- **Dispatcher** = control-ish launcher on SCRI (scrontab script / small module). It talks to the backend, claims (or reserves) work, writes a job payload file, `sbatch`s.
- **`worker run`** = compute one-shot (sister to bench): read file → run annotation → report complete/fail to backend → exit. No continuous claim loop inside the GPU allocation.

Naming note: avoid calling the one-shot mode “dispatcher mode” in the CLI (confuses launcher vs compute). Use `run` (or `execute`); document that the dispatcher **launches** `run`.

### 5.3 Recommended claim handoff (HPC)

1. Dispatcher authenticates to backend; registers as worker type `dispatcher` (or uses a service token).
2. For each available slot (capped per tick): **atomic claim** → write `job.json` (job id, lease, request body, backend URL, token) → `sbatch worker run --job-file ...`.
3. `worker run` renews lease / sends progress / complete / fail against that job id.
4. If `sbatch` fails after claim: dispatcher (or reaper) must **fail/requeue** that job so it is not stranded.

Alternative (also pull-safe): dispatcher only **peeks** queue depth, `sbatch`s N speculative `worker run --claim-one` processes that each call claim themselves. Over-spawn exits on 204. Prefer explicit claim-in-dispatcher when Slurm startup is expensive; prefer claim-in-worker when claim-before-sbatch stranding is the bigger risk. **Default for v1: claim inside `worker run` after the allocation starts**, and let the dispatcher only peek + cap concurrent Slurm jobs. Revisit if empty GPU allocations become costly.

**v1 decision locked in this spec:**  

- **Dispatcher:** peek queued count + list of running Slurm worker jobs; `sbatch` up to `min(queued, max_inflight - current)` run allocations.  
- **`worker run --claim-one`:** atomic claim after start; if 204, exit 0 quickly.  
- **Laptop serve:** same claim API.  

Races between serve and run are handled solely by atomic claim.

---

## 6. Backend responsibilities

Keep (from today’s coordinator):

- Job / batch create, list, result, history clear  
- Profiles, validate  
- Worker register / heartbeat / claim / progress / complete / fail  
- Lease reaper  
- Optional Mongo write on complete  
- Health + workers list for Fleet UI  

Add:

- **Accounts** (auth for public readers / submitters — scope in a follow-on task; at minimum gate `POST /jobs` and admin routes)  
- Public deploy config (`BACKEND_PUBLIC_URL`, TLS termination at host)  
- Dispatcher-friendly health signals (optional: last dispatcher poll time)  

Remove / stop using in production:

- Any in-process annotation execution path as the production drain (tests may keep `run_jobs_inline`)

Env rename (compat aliases required for one release):

- `COORDINATOR_URL` → `BACKEND_URL`  
- `COORDINATOR_API_BASE_URL` → `BACKEND_API_BASE_URL`  
- `COORDINATOR_PUBLIC_URL` → `BACKEND_PUBLIC_URL`  
- Package directory rename `coordinator/` → `backend/` can be a late task after behavior lands.

---

## 7. Frontend / Fleet health

Keep Fleet dashboard (`FleetDashboard`) as the ops view:

- Backend reachability, queue depth, Mongo (annotation) health  
- Connected workers: laptop `serve` agents (slots, heartbeat age, state)  
- Extend for HPC: show dispatcher last-seen / Slurm inflight if reported via heartbeat or a small dispatcher heartbeat endpoint  

Jobs page continues to poll backend for per-job phase progress (same as today when workers PATCH progress).

Copy/UI: replace user-visible “coordinator” with “backend” where it means the control plane; “fleet” covers laptops + HPC run workers.

---

## 8. Laptop + HPC together

| Concern | Behavior |
|---------|----------|
| Same queue | Yes — public backend |
| Claim races | Atomic claim; one winner |
| Setup for laptop | Install worker image/env; `BACKEND_URL` + token; `worker serve` |
| Setup for HPC | Image on registry; scrontab dispatcher; `worker run` in sbatch |
| Switching | Start/stop launchers; no second frontend |
| Inbound | Never required |

---

## 9. Relationship to prior “file + poster” idea

Lead’s sketch (download job file, delete from cloud queue, workers offline, dependent poster) optimizes for single-threaded cloud HTTP and offline GPU nodes. It conflicts with live progress and with dual-fleet claim unless carefully layered.

**This design:** keep the worker HTTP contract. Optionally later add a poster that batches `complete` calls if compute nodes cannot reach the backend — still the same API, not a second queue.

---

## 10. Open items (confirm during implementation)

1. Accounts model (anonymous read vs authenticated submit).  
2. Whether GPU nodes have outbound HTTPS to the public backend (assumed yes; if no, add poster).  
3. Scrontab host policy (login node vs dedicated).  
4. Package rename timing (`coordinator/` → `backend/`).  
5. Billing/chargeback when HPC is no longer free (out of scope; laptop serve is the escape hatch).

---

## 11. Success criteria

- [ ] Public FE + backend; no inbound to SCRI.  
- [ ] Dispatcher on scrontab can launch `worker run` for queued jobs.  
- [ ] Laptop `serve` can drain the same queue without code forks.  
- [ ] Two claimers never double-run one job.  
- [ ] Fleet UI shows connected serve workers; jobs page shows progress from run/serve.  
- [ ] Tag `pre-cloud-hpc-redesign-2026-08-24` remains a clean rollback to the LAN stack.  
