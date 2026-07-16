# Serve Dashboard + Coordinator/Frontend Job Progress Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the live terminal dashboard to `worker serve`, persist structured job progress on the coordinator via `PATCH /jobs/{id}/progress` (not heartbeats), and show phase + `n/m` sections on Jobs page tiles.

**Architecture:** Reuse bench dashboard/probes with a serve-oriented layout (uptime, no fixed batch total). Debounce `JobProgressEvent` → `CoordinatorClient.progress` with structured fields already on `JobProgress`. Extend SQLite job rows + API responses; frontend polls existing `GET /jobs` and renders richer tiles.

**Tech Stack:** Python worker/coordinator, pydantic contracts, SQLite job store, Next.js JobWorkspace.

**Spec:** `docs/superpowers/specs/2026-07-16-serve-dashboard-job-progress-design.md`

## Global Constraints

- Do **not** put per-job progress on worker heartbeats; heartbeats stay health/slots/drain only.
- Use existing `PATCH /jobs/{id}/progress` (already renews lease).
- Terminal dashboard refresh stays local (~0.5s); coordinator updates are debounced (~1–2s).
- Frontend keeps polling jobs list — no WebSocket/SSE in this plan.
- Prefer smallest diffs; no fleet/router redesign.
- `docs/` is gitignored — force-add design/plan if committing those files.
- Preserve `current_step` string for backward compatibility.

## File map

| File | Responsibility |
| --- | --- |
| `coordinator/job_store.py` | Persist structured progress columns; return them in `_row_to_job` |
| `coordinator/schemas.py` | Optional fields on `JobRecordResponse` |
| `coordinator/api.py` | Progress route writes structured fields |
| `shared/worker_contract.py` | Already has fields — verify only |
| `worker/client.py` | Send full `JobProgress` JSON |
| `worker/progress_reporter.py` (create) | Debounced progress reporter shared by serve |
| `worker/serve.py` | `on_progress` forward + dashboard + reporter wiring |
| `worker/bench_dashboard.py` | Serve-mode header/BATCH line helpers if needed |
| `frontend/components/JobWorkspace.js` | Tile label + percent from structured fields |
| `frontend/components/JobWorkspace.test.js` | Tile/progress tests |
| Tests under `tests/` | Store, API, client, serve dashboard |

---

### Task 1: Persist structured progress on coordinator jobs

**Files:**
- Modify: `coordinator/job_store.py`
- Modify: `coordinator/schemas.py`
- Modify: `coordinator/api.py` (progress handler)
- Test: `tests/test_coordinator_job_store.py` (or new `tests/test_job_progress_store.py`)

**Interfaces:**
- Consumes: `JobProgress` optional fields from `shared.worker_contract`
- Produces: `mark_step(job_id, current_step, *, phase=None, sections_done=None, sections_total=None, pass_name=None)`  
  Job dict keys: `progress_phase`, `sections_done`, `sections_total`, `pass_name`

- [ ] **Step 1: Write the failing test**

```python
def test_mark_step_persists_structured_progress(tmp_path):
    store = JobStore(tmp_path / "jobs.sqlite3")
    job = store.create_job({"profile": "mtb-h37rv", "locus": "Rv0001"})
    store.mark_running(job["id"])
    store.mark_step(
        job["id"],
        "extracting 3/12 sections (target)",
        phase="extracting",
        sections_done=3,
        sections_total=12,
        pass_name="target",
    )
    got = store.get_job(job["id"])
    assert got["current_step"] == "extracting 3/12 sections (target)"
    assert got["progress_phase"] == "extracting"
    assert got["sections_done"] == 3
    assert got["sections_total"] == 12
    assert got["pass_name"] == "target"
```

Adapt `JobStore` constructor/create_job to match existing test helpers in `tests/test_coordinator_job_store.py`.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_job_progress_store.py -v` (or the file you added)  
Expected: FAIL (unknown columns / kwargs)

- [ ] **Step 3: Implement schema migration + mark_step + row mapping**

1. Add columns via `_ensure_column` (same pattern as `current_step`):
   - `progress_phase TEXT`
   - `sections_done INTEGER`
   - `sections_total INTEGER`
   - `pass_name TEXT`
2. Extend `mark_step` to UPDATE those columns when provided (NULL-safe: only overwrite fields that are passed, or always set all four from kwargs with defaults None).
3. Include fields in `_row_to_job`.
4. Update `JobRecordResponse` with optional `progress_phase`, `sections_done`, `sections_total`, `pass_name`.
5. In `report_progress`, pass structured fields from `JobProgress` into `mark_step`.

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_coordinator_job_store.py tests/test_job_progress_store.py -v` plus any API progress tests that exist  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add coordinator/job_store.py coordinator/schemas.py coordinator/api.py tests/
git commit -m "$(cat <<'EOF'
Persist structured job progress fields on coordinator jobs.

EOF
)"
```

---

### Task 2: CoordinatorClient sends structured JobProgress

**Files:**
- Modify: `worker/client.py`
- Modify: `tests/test_worker_agent.py` (fake client / expectations)
- Test: extend or add client unit test

**Interfaces:**
- Produces: `progress(self, job_id, current_step, *, phase=None, sections_done=None, sections_total=None, pass_name=None, papers_done=None, papers_total=None)`  
  Or accept a `JobProgress` / dict. Prefer kwargs matching the model for minimal churn.

- [ ] **Step 1: Write failing test** that a fake transport / httpx mock receives JSON including `phase` and `sections_done`.

- [ ] **Step 2: Run test — expect FAIL**

- [ ] **Step 3: Implement client.progress payload**

```python
def progress(self, job_id, current_step, **fields):
    payload = {"current_step": current_step}
    for key in ("phase", "sections_done", "sections_total", "papers_done", "papers_total", "pass_name"):
        value = fields.get(key)
        if value is not None:
            payload[key] = value
    self._http.patch(
        f"/jobs/{job_id}/progress", headers=self._auth, json=payload
    ).raise_for_status()
```

Keep `client.progress(job_id, "running")` working (agent path).

- [ ] **Step 4: Run tests — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add worker/client.py tests/
git commit -m "$(cat <<'EOF'
Send structured fields on worker progress PATCH.

EOF
)"
```

---

### Task 3: Debounced progress reporter + wire serve execute path

**Files:**
- Create: `worker/progress_reporter.py`
- Modify: `worker/serve.py` (`_execute_job` + runtime wiring)
- Test: `tests/test_progress_reporter.py`, update serve/runtime tests as needed

**Interfaces:**
- Produces: `class ProgressReporter` with `report(job_id, event: JobProgressEvent)`, `flush(job_id)`, `close()`  
  Debounce interval default `1.5` sec (env `WORKER_PROGRESS_DEBOUNCE_SEC`).  
  Always send immediately on phase change; debounce same-phase section increments.  
  `serve._execute_job(..., on_progress=None)` forwards to `run_annotation_job`.

- [ ] **Step 1: Write failing tests**

```python
def test_progress_reporter_debounces_same_phase(monkeypatch):
    calls = []
    client = FakeClient(calls)
    reporter = ProgressReporter(client, debounce_sec=10.0)
    event = JobProgressEvent(phase="extracting", sections_done=1, sections_total=10, pass_name="target")
    reporter.report("j1", event)
    event2 = event.model_copy(update={"sections_done": 2})
    reporter.report("j1", event2)
    assert len(calls) == 1  # first immediate or first scheduled — define: first call immediate
    # advance time / flush
    reporter.flush("j1")
    assert calls[-1]["sections_done"] == 2


def test_progress_reporter_sends_immediately_on_phase_change():
    ...
```

Pick one clear debounce policy and document it in the module docstring:
**Policy:** send immediately on first event for a job and on every `phase` change; coalesce section increments within `debounce_sec`, flushing the latest.

- [ ] **Step 2: Run tests — expect FAIL**

- [ ] **Step 3: Implement ProgressReporter + serve wiring**

1. Implement reporter using `threading.Timer` or monotonic timestamps checked on each `report` / a small helper thread — keep it simple and tested.
2. Map `JobProgressEvent` → `format_current_step` + structured kwargs.
3. In `serve.py`:
   - Change `_execute_job` to accept/forward `on_progress`.
   - Construct `ProgressReporter(client)` when coordinator client exists.
   - Pass `on_progress=lambda event: reporter.report(job_id, event)` via runtime (signature detection already in `WorkerRuntime`).
   - On complete/fail paths already in job source, `reporter.flush(job_id)`.

Note: `WorkerRuntime` already passes `on_progress` when `execute_fn` supports it — serve was the missing forwarder.

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_progress_reporter.py tests/test_worker_runtime_progress.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add worker/progress_reporter.py worker/serve.py tests/
git commit -m "$(cat <<'EOF'
Debounce structured progress reports from serve jobs to the coordinator.

EOF
)"
```

---

### Task 4: Serve-mode live dashboard

**Files:**
- Modify: `worker/bench_dashboard.py` (serve layout / mode)
- Modify: `worker/serve.py`
- Test: `tests/test_bench_dashboard.py`, `tests/test_worker_serve.py` (or new)

**Interfaces:**
- Consumes: `BenchDashboard.run_live`, `configure_bench_logging` (extract shared logging helpers to `worker/dashboard_logging.py` only if copy-paste hurts; otherwise import from bench or duplicate thin wrappers — prefer extracting `configure_bench_logging` to `worker/logging_setup.py` if serve needs it cleanly).
- Produces: serve dashboard when TTY and `WORKER_SERVE_DASHBOARD` != `0`; `--no-dashboard` flag on serve CLI if argparse exists.

- [ ] **Step 1: Write failing render test for serve layout**

```python
def test_render_dashboard_serve_mode_uses_uptime_and_no_total():
    text = render_dashboard(
        snapshot={"jobs_completed": 12, "jobs_failed": 1, "jobs_total": None, "active": []},
        hw={"gpus": None, "gpu_error": "nvidia-smi not found", "cpu_percent": 10.0, "ram": "1/16 GB"},
        meta={"mode": "serve", "fleet": "1x2", "slots": 2, "tier": "warm_stack", "elapsed_s": 3661},
    )
    assert "serve" in text
    assert "uptime" in text.lower() or "1:01:01" in text
    assert "SERVE" in text or "12 done" in text
    assert "/100" not in text  # no fake batch total
```

- [ ] **Step 2: Run test — expect FAIL**

- [ ] **Step 3: Implement serve layout + wire serve.main**

1. When `meta["mode"] == "serve"`: header uses `uptime` label; summary line `SERVE  N done │ F failed │ R running` (idle when R=0).
2. Extract or reuse `_run_with_dashboard` pattern in serve after fleet/router ready, before `runtime.run()`.
3. Default log file: `$WORKER_OUTPUT_DIR/worker-serve.log` or cwd `worker-serve.log`.
4. Env: `WORKER_SERVE_DASHBOARD` (default on for TTY); `--no-dashboard` if serve has CLI flags — add if missing.
5. Document that Docker/systemd need `-t` / TTY for Live UI.

- [ ] **Step 4: Run tests — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add worker/bench_dashboard.py worker/serve.py tests/
git commit -m "$(cat <<'EOF'
Enable live dashboard for worker serve mode.

EOF
)"
```

---

### Task 5: Frontend job tiles show sections progress

**Files:**
- Modify: `frontend/components/JobWorkspace.js`
- Modify: `frontend/components/JobWorkspace.test.js`
- Modify: `frontend/lib/api.js` only if response typing helpers need it (usually not)

**Interfaces:**
- Consumes: job fields `progress_phase`, `sections_done`, `sections_total`, `pass_name`, `current_step`
- Produces: updated `JobTile` subtitle + `progressPercent(job)` (ortholog-aware half/half bar)

- [ ] **Step 1: Write failing frontend tests**

```javascript
test("job tile shows sections progress when structured fields present", () => {
  // render JobTile with job { status: "running", progress_phase: "extracting", sections_done: 3, sections_total: 12, pass_name: "target", current_step: "extracting 3/12 sections (target)", request: {...} }
  // assert text matching /3\/12/ and /extracting/
});

test("progressPercent maps target-only progress across the full bar", () => {
  // No ortholog progress has appeared yet, so target pass uses the full bar.
  // 3/12 target → 25%.
  assert.equal(
    progressPercent({
      status: "running",
      pass_name: "target",
      sections_done: 3,
      sections_total: 12,
    }),
    25,
  );
});

test("progressPercent maps ortholog pass into second half of bar", () => {
  // ortholog 1/2 → 50 + 50*(1/2) = 75
  assert.equal(
    progressPercent({
      status: "running",
      pass_name: "ortholog",
      progress_phase: "ortholog_extracting",
      sections_done: 1,
      sections_total: 2,
    }),
    75,
  );
});

test("progressPercent holds at 50 while ortholog total unknown", () => {
  assert.equal(
    progressPercent({
      status: "running",
      pass_name: "ortholog",
      progress_phase: "ortholog_fetching",
      sections_done: 0,
      sections_total: null,
    }),
    50,
  );
});
```

Export `progressPercent` for testing if currently module-private (or test via rendered progressbar width/aria). Use a single rounding rule (`Math.round`) and assert that consistently.

- [ ] **Step 2: Run frontend test — expect FAIL**

Run: `npm test -- JobWorkspace` (or project’s equivalent)

- [ ] **Step 3: Implement tile UI**

1. Prefer structured fields for label:  
   `extracting · 3/12 sections (target)`  
   else `stepLabels[current_step]`. Subtitle always shows **current-pass** `n/m`, not a combined denominator.
2. `progressPercent` (see design “Progress bar (ortholog-aware)”):
   - `completed` / `failed` → 100
   - `pass_name === "ortholog"` (or phase starts with `ortholog_`):
     - if `sections_total` missing/0 → **50**
     - else `50 + 50 * (sections_done / sections_total)` (clamp ≤ 99 while running)
   - else (target pass):
     - if no ortholog progress has appeared yet and `sections_total` known → `100 * (sections_done / sections_total)` (clamp ≤ 99 while running)
     - aggregating / near-done target before ortholog is known → ~95–99
     - else coarse heuristic
   - If an ortholog progress event appears, the UI is allowed to remap into the two-pass model at that point; before that, do not reserve half the bar.
3. Keep spinner behavior for running jobs.

- [ ] **Step 4: Run frontend + any coordinator contract tests — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add frontend/components/JobWorkspace.js frontend/components/JobWorkspace.test.js
git commit -m "$(cat <<'EOF'
Show section progress on Jobs page tiles with ortholog-aware bar.

EOF
)"
```

---

### Task 6: Docs + end-to-end self-check

**Files:**
- Modify: `worker/README.md` (serve dashboard + progress debounce)
- Modify: `docs/deploy-worker-bench-hpc.md` only if needed; add a short note in worker README for serve TTY
- Force-add design/plan under `docs/superpowers/`

- [ ] **Step 1: Document serve dashboard flags and that progress uses PATCH not heartbeat**
- [ ] **Step 2: Run suites**

```bash
pytest tests/test_job_progress.py tests/test_progress_reporter.py tests/test_bench_dashboard.py \
  tests/test_worker_runtime_progress.py tests/test_coordinator_job_store.py -v
# plus new store/API tests
npm test -- JobWorkspace
```

- [ ] **Step 3: Commit docs**

```bash
git add worker/README.md
git add -f docs/superpowers/specs/2026-07-16-serve-dashboard-job-progress-design.md \
  docs/superpowers/plans/2026-07-16-serve-dashboard-job-progress.md
git commit -m "$(cat <<'EOF'
Document serve dashboard and job progress to coordinator/frontend.

EOF
)"
```

---

## Spec coverage check

| Spec requirement | Task |
| --- | --- |
| No progress on heartbeats | Constraint + Tasks 2–3 |
| Serve live dashboard | 4 |
| Debounced PATCH progress with structured fields | 2–3 |
| Persist phase/sections on jobs | 1 |
| Frontend tiles n/m + step | 5 |
| Ortholog-aware progress bar (target 0–50%, ortholog 50–100%) | 5 |
| Poll jobs (no WS) | 5 (existing poll) |
| Docs | 6 |

## Out of scope (follow-ups)

- Heartbeat-carried progress summaries.
- WebSocket/SSE live jobs.
- Coordinator queue depth on serve dashboard.
- Bench mode reporting progress to coordinator (bench is local-only today).
