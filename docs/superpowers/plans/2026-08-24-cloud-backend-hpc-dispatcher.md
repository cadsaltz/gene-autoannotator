# Cloud Backend + HPC Dispatcher Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Evolve the LAN coordinator stack into a single public backend job queue with pull-only laptop `serve` and HPC dispatcher → `worker run`, without forking a second web architecture.

**Architecture:** One backend owns and persists the queue; all compute initiates outbound HTTPS (claim/heartbeat/progress/complete). HPC scrontab dispatcher peeks and `sbatch`s one-shot `worker run --claim-one`; spare laptops run `worker serve` against the same API. Atomic SQLite claims prevent double-assignment. Frontend Fleet/Jobs continue to poll the backend.

**Tech Stack:** FastAPI + SQLite (backend), Next.js (frontend), Python worker (serve / run / bench), Slurm + scrontab + Docker (HPC), optional MongoDB (annotations).

**Design spec:** `docs/superpowers/specs/2026-08-24-cloud-backend-hpc-dispatcher-design.md`  
**Rollback tag:** `pre-cloud-hpc-redesign-2026-08-24`  
**Branch:** `redesign/cloud-backend-hpc-dispatcher`

## Global Constraints

- Pull-only: backend never dials workers/dispatcher/HPC/laptops.
- Singular queue ownership: only the backend persists jobs; no HPC job SQLite.
- Atomic claim is the only `queued → running` transition for fleet compute.
- Preserve `autoannotation/` behavior; do not rewrite prompts/models for this redesign.
- Keep `worker bench` for standalone JSONL; do not require backend for bench.
- Env aliases: accept legacy `COORDINATOR_*` names while introducing `BACKEND_*`.
- Do not implement a second web stack or “slurm mode” that replaces the backend queue.
- TDD for new claim/`run`/dispatcher logic; update docs when renaming user-facing terms.
- Frequent commits; leave door open for laptop + HPC concurrently.

---

## File map (target)

| Path | Role |
|------|------|
| `backend/` (later rename from `coordinator/`) | Public control plane |
| `dispatcher/` (new) | Scrontab entry: peek queue, cap inflight, `sbatch` |
| `worker/serve.py` | Continuous claim loop (laptops) |
| `worker/run.py` (new) | One-shot Slurm mode: claim-one or job-file → annotate → complete → exit |
| `worker/bench.py` | Unchanged purpose (local JSONL) |
| `worker/client.py` | Backend HTTP client (rename helpers gradually) |
| `shared/job_contract.py`, `shared/worker_contract.py` | Wire DTOs |
| `frontend/components/FleetDashboard.js` | Fleet health UI |
| `frontend/lib/api.js` | `BACKEND_API_BASE_URL` (+ legacy fallback) |
| `deploy/slurm/worker-run.sbatch` (new) | Slurm template for `worker run` |
| `deploy/scripts/` | Dispatcher install / scrontab helpers |

---

### Task 1: Document freeze + env alias layer

**Files:**
- Create: `docs/superpowers/specs/2026-08-24-cloud-backend-hpc-dispatcher-design.md` (already drafted — verify committed)
- Modify: `coordinator/api.py` (startup log lines for public URL)
- Modify: `worker/client.py` (read `BACKEND_URL` then `COORDINATOR_URL`)
- Modify: `frontend/lib/api.js` and `frontend/.env.example`
- Modify: `coordinator.env.example` → also document `BACKEND_*` keys
- Test: `tests/test_backend_url_alias.py` (new)

**Interfaces:**
- Consumes: existing `COORDINATOR_URL` / `COORDINATOR_API_BASE_URL`
- Produces: `resolve_backend_url()` helper used by worker client and documented for FE

- [ ] **Step 1: Write the failing test**

```python
# tests/test_backend_url_alias.py
import os
from worker.env_urls import resolve_backend_url

def test_backend_url_prefers_backend_over_coordinator(monkeypatch):
    monkeypatch.setenv("BACKEND_URL", "https://api.example/backend")
    monkeypatch.setenv("COORDINATOR_URL", "http://legacy:8000")
    assert resolve_backend_url() == "https://api.example/backend"

def test_backend_url_falls_back_to_coordinator(monkeypatch):
    monkeypatch.delenv("BACKEND_URL", raising=False)
    monkeypatch.setenv("COORDINATOR_URL", "http://legacy:8000")
    assert resolve_backend_url() == "http://legacy:8000"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_backend_url_alias.py -v`  
Expected: FAIL (module missing)

- [ ] **Step 3: Implement `worker/env_urls.py` and wire `worker/client.py`**

```python
# worker/env_urls.py
import os

def resolve_backend_url() -> str:
    url = (os.getenv("BACKEND_URL") or os.getenv("COORDINATOR_URL") or "").rstrip("/")
    if not url:
        raise RuntimeError("BACKEND_URL (or legacy COORDINATOR_URL) is required")
    return url
```

Update client construction to call `resolve_backend_url()`.

- [ ] **Step 4: Mirror alias in frontend `lib/api.js`**

Prefer `BACKEND_API_BASE_URL`, fall back to `COORDINATOR_API_BASE_URL`, then `BACKEND_API_BASE_URL` legacy `BACKEND_API_BASE_URL` / existing `BACKEND_API_BASE_URL` pattern already used — keep `COORDINATOR_API_BASE_URL` and old `BACKEND_API_BASE_URL` both working.

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_backend_url_alias.py -v`  
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add docs/superpowers/specs/2026-08-24-cloud-backend-hpc-dispatcher-design.md \
  worker/env_urls.py worker/client.py frontend/lib/api.js frontend/.env.example \
  coordinator.env.example tests/test_backend_url_alias.py
git commit -m "$(cat <<'EOF'
docs: freeze cloud/HPC pull-only contract and add BACKEND_URL aliases

EOF
)"
```

---

### Task 2: Harden atomic claim for multi-claimer fleets

**Files:**
- Modify: `coordinator/job_store.py` (`assign_job_to_worker`)
- Modify: `coordinator/api.py` (`claim_job`)
- Test: `tests/test_job_claim_race.py` (new)

**Interfaces:**
- Consumes: `JobStore.assign_job_to_worker(worker_id, *, lease_seconds)`
- Produces: Same method remains the only fleet claim path; document that peek endpoints never transition status

- [ ] **Step 1: Write a concurrent claim test**

```python
# tests/test_job_claim_race.py
from concurrent.futures import ThreadPoolExecutor
from coordinator.job_store import JobStore

def test_two_claimers_only_one_wins(tmp_path):
    store = JobStore(tmp_path / "jobs.sqlite3")
    job = store.create_job({"profile": "mtb-h37rv", "locus": "Rv0001"})
    results = []

    def claim(worker_id):
        results.append(store.assign_job_to_worker(worker_id, lease_seconds=60))

    with ThreadPoolExecutor(max_workers=2) as pool:
        pool.submit(claim, "serve-a")
        pool.submit(claim, "run-b")
        # wait
    won = [r for r in results if r is not None]
    assert len(won) == 1
    assert store.get_job(job["id"])["status"] == "running"
```

(Adapt `create_job` to the real JobStore API used in existing tests.)

- [ ] **Step 2: Run test — fix store if it fails under concurrency**

Run: `pytest tests/test_job_claim_race.py -v`  
Expected: PASS with `BEGIN IMMEDIATE` (already present); strengthen if needed.

- [ ] **Step 3: Add read-only peek helper (no status change)**

```python
def count_queued_jobs(self) -> int:
    with self._connect() as connection:
        row = connection.execute(
            "SELECT COUNT(*) AS n FROM annotation_jobs WHERE status = ?",
            ("queued",),
        ).fetchone()
        return int(row[0])
```

Expose `GET /jobs/queue-summary` or extend `GET /health` / existing jobs list so the dispatcher can peek without claiming.

- [ ] **Step 4: Tests + commit**

```bash
git commit -m "$(cat <<'EOF'
fix(backend): prove atomic claim under concurrent serve/run claimers

EOF
)"
```

---

### Task 3: Add `worker run` one-shot mode

**Files:**
- Create: `worker/run.py`
- Modify: `worker/__main__.py` (subcommand `run`)
- Modify: `worker/runtime.py` (reuse job execution path from serve/bench)
- Test: `tests/test_worker_run_claim_one.py` (new)
- Docs: `worker/README.md`

**Interfaces:**
- Consumes: `CoordinatorClient.claim` / `progress` / `complete` / `fail`; `WorkerRuntime` job execution
- Produces: CLI `python -m worker run --claim-one` and `python -m worker run --job-file PATH`

- [ ] **Step 1: Failing test — claim-one exits 0 on empty queue**

```python
def test_run_claim_one_exits_clean_when_no_job(monkeypatch, tmp_path):
    # stub client.claim → None / 204
    # invoke run_main(claim_one=True)
    # assert exit code 0 and no annotation invoked
```

- [ ] **Step 2: Implement minimal `run` mode**

Behavior:

1. Resolve backend URL + token.
2. If `--claim-one`: register ephemeral worker id (or reuse `WORKER_NAME`+pid), claim once; if none, exit 0.
3. If `--job-file`: load job payload (id + request); skip claim.
4. Execute via existing runtime/subprocess path (same as serve slot).
5. On success: `complete`; on failure: `fail`.
6. Always exit (no claim loop).

- [ ] **Step 3: Wire argparse in `worker/__main__.py`**

```text
python -m worker run --claim-one
python -m worker run --job-file /path/job.json
```

- [ ] **Step 4: README — three modes table (serve / run / bench)**

- [ ] **Step 5: Commit**

```bash
git commit -m "$(cat <<'EOF'
feat(worker): add one-shot run mode for Slurm allocations

EOF
)"
```

---

### Task 4: Dispatcher package (peek + sbatch)

**Files:**
- Create: `dispatcher/__init__.py`
- Create: `dispatcher/__main__.py`
- Create: `dispatcher/loop.py`
- Create: `deploy/slurm/worker-run.sbatch`
- Create: `deploy/scripts/install-dispatcher.sh` (optional stub)
- Test: `tests/test_dispatcher_loop.py` (new)

**Interfaces:**
- Consumes: backend `GET` queue depth (peek), `sbatch` command template
- Produces: `python -m dispatcher once` (scrontab-friendly) and `python -m dispatcher`

Behavior for v1 (per design spec):

1. Read env: `BACKEND_URL`, `WORKER_API_TOKEN`, `DISPATCHER_MAX_INFLIGHT`, `DISPATCHER_SBATCH_SCRIPT`.
2. Peek queued count from backend.
3. Count already-inflight Slurm jobs (tag/name convention or `squeue -u $USER -n gene-autoannotator-run`).
4. `to_launch = min(queued, max_inflight - inflight)`.
5. For `_ in range(to_launch)`: `sbatch deploy/slurm/worker-run.sbatch` (script runs `python -m worker run --claim-one`).
6. Exit 0 (scrontab runs periodically). Do **not** delete jobs from the queue except via worker claim.

- [ ] **Step 1: Unit-test pure planning function**

```python
def test_plan_launches():
    assert plan_launches(queued=5, inflight=2, max_inflight=4) == 2
    assert plan_launches(queued=0, inflight=0, max_inflight=4) == 0
    assert plan_launches(queued=10, inflight=4, max_inflight=4) == 0
```

- [ ] **Step 2: Implement `dispatcher/loop.py` + `__main__.py`**

- [ ] **Step 3: Add example `worker-run.sbatch`**

```bash
#!/bin/bash
#SBATCH --job-name=gene-autoannotator-run
#SBATCH --gpus=1
# … site-specific …
python -m worker run --claim-one
```

- [ ] **Step 4: Tests + commit**

```bash
git commit -m "$(cat <<'EOF'
feat(dispatcher): add scrontab peek-and-sbatch launcher for worker run

EOF
)"
```

---

### Task 5: Keep `serve` on the same pull path (verify + docs)

**Files:**
- Modify: `worker/README.md`, `coordinator/README.md` (or backend README)
- Test: existing serve/client tests — ensure they use `resolve_backend_url`

- [ ] **Step 1: Confirm `worker serve` only uses claim/heartbeat/complete (no push from backend)**

- [ ] **Step 2: Document dual-fleet example**

```bash
# laptop
BACKEND_URL=https://api.example WORKER_API_TOKEN=… python -m worker serve

# HPC scrontab
*/5 * * * * cd /opt/gene-autoannotator && .venv/bin/python -m dispatcher once
```

- [ ] **Step 3: Commit docs**

```bash
git commit -m "$(cat <<'EOF'
docs: dual-fleet serve + dispatcher pull from one backend queue

EOF
)"
```

---

### Task 6: Frontend Fleet / Jobs copy and backend base URL

**Files:**
- Modify: `frontend/components/FleetDashboard.js`
- Modify: `frontend/components/JobWorkspace.js` (user-visible “coordinator” → “backend” where appropriate)
- Modify: `frontend/lib/api.js`, `frontend/.env.example`
- Test: `frontend/components/FleetDashboard.test.js`

- [ ] **Step 1: Update labels** — “Backend”, “Fleet workers”, keep slot/heartbeat tiles

- [ ] **Step 2: Optional dispatcher signal** — if `GET /workers` includes a dispatcher registration, show “HPC dispatcher” card; otherwise document as follow-up

- [ ] **Step 3: Ensure jobs polling unchanged (still `GET /jobs` every 5s)**

- [ ] **Step 4: `npm test` + commit**

```bash
git commit -m "$(cat <<'EOF'
feat(frontend): point fleet UI at public backend naming

EOF
)"
```

---

### Task 7: Deploy path for public backend + SCRI dispatcher

**Files:**
- Modify: `deploy/compose/docker-compose.coordinator.yml` → compose for frontend+backend (rename file in a follow commit if needed)
- Create: `docs/deploy-cloud-backend-hpc-dispatcher.md`
- Modify: root `README.md` “Current Limitations” / web architecture section (replace stale in-process claims)

- [ ] **Step 1: Write deploy doc** covering: cloud FE+backend, Mongo, SCRI scrontab, laptop optional serve, rollback tag

- [ ] **Step 2: Update README architecture blurb to match design spec**

- [ ] **Step 3: Commit**

```bash
git commit -m "$(cat <<'EOF'
docs: deploy guide for public backend and HPC dispatcher

EOF
)"
```

---

### Task 8: Package rename `coordinator` → `backend` (late, mechanical)

**Files:**
- Move: `coordinator/` → `backend/`
- Update imports, uvicorn target `backend.api:app`, tests, compose, docs
- Keep thin shim `coordinator/api.py` re-export for one release **or** document breaking change in CHANGELOG

- [ ] **Step 1: Move package; fix imports until `pytest` green**

- [ ] **Step 2: Update compose / systemd / README entrypoints**

- [ ] **Step 3: Commit**

```bash
git commit -m "$(cat <<'EOF'
refactor: rename coordinator package to backend

EOF
)"
```

---

### Task 9: Accounts gate (minimal)

**Files:**
- Modify: `backend/api.py` (or coordinator until rename)
- Create: `backend/auth.py`
- Test: `tests/test_accounts_gate.py`

**Scope (minimal v1):** shared submit token or basic auth for `POST /jobs` and mutating admin routes; public read of completed annotations can stay open or require login — **confirm with lead before coding**. If lead defers accounts, mark this task skipped and leave an issue note in the deploy doc.

- [ ] **Step 1: Agree auth model with lead (blocker)**

- [ ] **Step 2: Implement agreed gate + tests**

- [ ] **Step 3: Commit**

---

### Task 10: End-to-end verification checklist

**Files:** none (manual / scripted smoke)

- [ ] **Step 1: Local dual claimer smoke**

```bash
# terminal 1
BACKEND_URL=http://127.0.0.1:8000 WORKER_API_TOKEN=dev python -m worker serve
# terminal 2
BACKEND_URL=http://127.0.0.1:8000 WORKER_API_TOKEN=dev python -m worker run --claim-one
# submit two jobs via POST /jobs — each claimer gets at most one; no duplicate runs
```

- [ ] **Step 2: Dispatcher dry-run** (`DISPATCHER_SBATCH_SCRIPT=echo` or mock) proves launch count math

- [ ] **Step 3: Confirm rollback**

```bash
git checkout pre-cloud-hpc-redesign-2026-08-24
```

- [ ] **Step 4: Record results in `.superpowers/sdd/` or PR description**

---

## Spec coverage checklist

| Design requirement | Task |
|--------------------|------|
| Pull-only / no inbound | 1, 4, 5, 7 |
| Singular queue on backend | 2, 4, 5 |
| Atomic claim / races | 2, 3, 10 |
| Rename roles (backend / dispatcher / worker) | 1, 6, 8 |
| serve + run + bench modes | 3, 5 |
| serve drains backend | 5 |
| Dispatcher scrontab + sbatch | 4, 7 |
| Fleet/health UI | 6 |
| Laptop + HPC together | 5, 10 |
| Accounts | 9 |
| Rollback tag | (created) + Task 10 |

## Placeholder / consistency review

- Claim path names match existing `assign_job_to_worker` / `/workers/.../claim`.
- `worker run` is the Slurm one-shot name (not “dispatcher mode”) to avoid colliding with the dispatcher package.
- Peek never deletes queue rows; only claim transitions status.
- Boss file+poster path deferred; not required for v1 dual-fleet.
