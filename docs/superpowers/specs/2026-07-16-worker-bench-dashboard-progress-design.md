# Worker bench dashboard + reusable job progress

**Date:** 2026-07-16  
**Status:** approved for planning  
**Scope:** (1) reusable structured job progress; (2) live terminal dashboard for `worker bench`. Coordinator/frontend UI deferred; contract must be reusable.

## Goals

- Replace noisy bench stdout with an in-place TUI dashboard (jobs + hardware).
- Send full logs to a file for debugging.
- Emit structured per-job progress from the annotation pipeline so bench (now) and coordinator/API (later) can consume the same events.
- Do **not** query Ollama (`ps`/`list`/`tags`) from the dashboard refresh path.

## Non-goals

- Wiring live progress into the frontend UI in this change.
- Per-token / per-LLM-call progress bars.
- Changing fleet sizing, keep_alive, or model routing.

## Decisions

| Topic | Choice |
| --- | --- |
| Verbose logs | File only when dashboard is active (option A) |
| Progress metric | Phase + `sections_done` / `sections_total` (increment after section consensus) |
| Progress reuse | Shared pydantic model + emission hooks; extend existing `JobProgress` for future API |
| Job transport | Subprocess jobs emit NDJSON progress lines on **stderr**; stdout remains result JSON |
| Dashboard lib | `rich.Live` (already in `requirements.txt`) |
| Hardware probes | `nvidia-smi` + `/proc` (CPU/RAM); never Ollama CLI/HTTP for the dashboard |
| Fallback | Non-TTY / `--no-dashboard`: keep plain `_progress` lines; still write log file if configured |

## Progress model

### Phases

`fetching` → `extracting` → `aggregating` → (optional ortholog) `ortholog_fetching` → `ortholog_extracting` → `ortholog_aggregating` → `finalizing`

### Event fields (`shared` contract)

```text
JobProgressEvent
  job_id: str | None
  phase: Literal[...]
  sections_done: int
  sections_total: int | None   # None while still fetching / unknown
  papers_done: int | None      # optional; papers with all sections consensus'd
  papers_total: int | None
  pass_name: Literal["target", "ortholog"] | None
  message: str | None          # human one-liner for current_step fallback
```

### Counting rules

1. Job starts → emit `phase=fetching`, `sections_done=0`, `sections_total=None`.
2. After relevance selection, **pre-scan** selected papers for available sections (abstract/results/discussion) with **no LLM calls** → set `sections_total=N`, `papers_total=P`, emit `phase=extracting`, `sections_done=0`.
3. After each section **consensus** completes → `sections_done += 1`, emit update.
4. When `sections_done == sections_total` for the pass → emit `phase=aggregating` (or ortholog equivalent).
5. Ortholog pass resets section counters for that pass (or uses cumulative totals with a clear `pass_name`); dashboard shows pass + counts. Prefer **per-pass counters** plus a one-line pass label to avoid a jumping denominator mid-job without explanation.
6. Format `current_step` string for existing coordinator field, e.g. `extracting 3/18 sections (target)`.

### Emission path

```text
autoannotation (progress_cb)
  → job_main stderr NDJSON {"type":"progress", ...}
  → executor parses lines → runtime on_progress(job_id, event)
  → bench dashboard state
  → (later) worker.client.progress / PATCH /jobs/{id}/progress with extended JobProgress
```

Extend `shared.worker_contract.JobProgress` with optional structured fields (`phase`, `sections_done`, `sections_total`, …) while keeping `current_step: str` required for backward compatibility.

## Dashboard

### Layout (TTY)

```text
gene-autoannotator bench │ mode │ fleet │ slots │ tier │ elapsed
BATCH  done/total │ failed │ running │ queued
────────────────────────────────────────
JOBS (one line per active slot)
  spinner job_id locus  phase  sections_done/total  elapsed
────────────────────────────────────────
GPU lines from nvidia-smi (or clear unavailable message)
CPU / ollama-proc CPU / system RAM from /proc + ps sampling
────────────────────────────────────────
last error / status footer
```

### Refresh

- Interval ~1.0s (configurable env, default 1s).
- In-place redraw via `rich.Live`.
- Probes run in the dashboard thread only; failures show explicit “unavailable” text.

### Logging

- When dashboard on: root/app loggers → rotating or plain file under output/report dir (e.g. `WORKER_LOG_FILE` or default beside report).
- Job subprocess stderr: progress NDJSON consumed by parent; non-progress lines appended to the log file (not the Live display).

### Hardware

- GPUs: parse `nvidia-smi --query-gpu=index,name,utilization.gpu,memory.used,memory.total,temperature.gpu --format=csv,noheader,nounits`.
- If missing/empty/unparseable: one dashboard line stating why.
- CPU%: `/proc/stat` delta.
- RAM: `/proc/meminfo`.
- Ollama process CPU: sum matching process names from `/proc` or `psutil` (already a dependency via requirements-web; prefer stdlib `/proc` in worker image if psutil not guaranteed in worker-only path — use `/proc` to avoid new coupling).

## Testing

- Unit tests for progress event model and `current_step` formatting.
- Unit tests for section pre-scan counting helper.
- Unit tests for stderr NDJSON progress parsing in executor.
- Unit tests for nvidia-smi / meminfo parsers with fixtures.
- Dashboard render smoke test (non-TTY / string console) without Live loop.

## Rollout

1. Ship progress events + file logging + dashboard behind default-on for TTY bench.
2. `--no-dashboard` / `WORKER_BENCH_DASHBOARD=0` for HPC log capture when stdout must be linear.
3. Later: map events into coordinator `JobProgress` and frontend.
