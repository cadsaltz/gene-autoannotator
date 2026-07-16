# Serve dashboard + coordinator/frontend job progress

**Date:** 2026-07-16  
**Status:** approved for planning  
**Depends on:** bench dashboard + `JobProgressEvent` (already landed)

## Heartbeat vs progress API (decision)

**Do not put per-job progress on heartbeats.** Use (and extend) the existing `PATCH /jobs/{id}/progress` path.

| | Heartbeat | Progress PATCH |
| --- | --- | --- |
| Scope | Worker health (slots, CPU, drain) | One job’s phase / sections |
| Existing | `POST /workers/{id}/heartbeat` | `PATCH /jobs/{id}/progress` (already renews lease) |
| Cadence | ~15s | Debounce ~1–2s per job (fine for UI; terminal dashboard stays local/fast) |
| Frontend | Fleet page | Jobs list already polls jobs |

Stuffing all active jobs into every heartbeat mixes concerns, forces coarser updates, and duplicates what progress already does. Frontend does **not** need WS/SSE yet — keep polling `GET /jobs` (~few seconds).

## Goals

1. Live terminal dashboard for `worker serve` (TTY), adapted for open-ended claim loop.
2. Structured progress persisted on coordinator job records.
3. Jobs page tiles show phase + `n/m` sections (and a better progress bar).

## Non-goals

- WebSocket/SSE job streaming.
- Progress on heartbeats.
- Changing fleet/router/Ollama sizing.
- Matching terminal dashboard refresh rate in the browser.

## Architecture

```text
annotation progress_cb
  → job stderr NDJSON (already)
  → WorkerRuntime.on_progress (already)
  → [NEW] debounced CoordinatorClient.progress(job_id, JobProgress)
  → coordinator mark_step + structured columns
  → GET /jobs includes phase / sections_*
  → JobWorkspace JobTile renders step + n/m

serve main
  → [NEW] same Live dashboard as bench (serve layout: uptime, no fixed total)
```

## Data model

Persist on `annotation_jobs` (in addition to existing `current_step` string):

- `progress_phase TEXT NULL`
- `sections_done INTEGER NULL`
- `sections_total INTEGER NULL`
- `pass_name TEXT NULL`

`current_step` remains the human one-liner (`format_current_step(event)`) for backward compatibility.

`JobProgress` in `shared/worker_contract.py` already has optional structured fields — wire them through store + API responses.

## Serve dashboard layout

```text
gene-autoannotator serve │ uptime H:MM:SS │ fleet … │ slots … │ tier …

SERVE  12 done │ 1 failed │ 2 running │ idle|claiming

─── JOBS (active) ───
  ⠹ job-abc  |  Rv0001  |  phase extracting  |  sections 3/12  |  elapsed 2m

─── GPU / CPU / RAM ───  (same probes as bench)
```

No `jobs_total` / fake queued count unless coordinator queue depth is fetched later (out of scope).

## Worker progress → coordinator

- In serve (and optionally bench if coordinator-backed later): on each runtime progress event, call `client.progress` with full `JobProgress`.
- **Debounce** per `job_id` (~1–2s), always flush on job complete/fail and on phase change.
- Update `CoordinatorClient.progress` to send structured fields (today only `current_step`).
- Forward `on_progress` from `serve._execute_job` (same fix as bench).

## Frontend

- Extend job JSON consumers with optional `progress_phase`, `sections_done`, `sections_total`, `pass_name`.
- `JobTile`: show e.g. `extracting · 3/12 sections (target)` when structured fields present; fall back to `stepLabels[current_step]`.
- Polling interval: keep existing jobs poll (or ~3–5s if currently slower); no new channel.

### Progress bar (ortholog-aware)

Worker progress is **per-pass** (`pass_name` + `sections_done` / `sections_total` reset for ortholog). The frontend should use the target pass as the full bar **until an ortholog pass is confirmed** by an `ortholog_*` progress event. This avoids penalizing target-only jobs that never take the ortholog path.

| Stage | Bar mapping |
| --- | --- |
| Target pass, no ortholog seen yet, sections known | `0–99%` ← `sections_done / sections_total` while running |
| Target aggregating / finalizing before ortholog is known | hold near **95–99%** |
| Ortholog confirmed (`pass_name=ortholog` or phase starts `ortholog_`) | remap into two-pass view; target is treated as **50%** complete |
| Ortholog fetching (`sections_total` still null) | hold **50%** |
| Ortholog pass (`pass_name=ortholog`), sections known | `50–100%` ← `50 + 50 * (sections_done / sections_total)` |
| Completed | **100%** |
| Failed | **100%** (tone indicates failure; bar full) |
| No structured fields | keep coarse status heuristic |

Rationale: only the worker knows whether an ortholog pass was actually triggered (override or low cumulative relevance). Target-only jobs should use the whole bar. When an ortholog event appears, the UI may visually remap from target-only progress into the two-pass model; from then on the ortholog pass fills the second half. This can make the bar appear to move backward once, but only at the moment the scope legitimately expands.

Tile subtitle still shows the **current** pass `n/m` (not a fake combined denominator).

## Testing

- Serve dashboard enablement / layout unit tests.
- Coordinator `mark_step` persists structured fields; GET job returns them.
- Client progress payload includes fields.
- Frontend unit tests for tile label + percent with/without structured progress.
