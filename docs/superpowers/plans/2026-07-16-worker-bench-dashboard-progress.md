# Worker Bench Dashboard + Job Progress Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add reusable structured job progress from the annotation pipeline, and a live in-place bench dashboard (jobs + hardware) with verbose logs redirected to a file.

**Architecture:** Annotation code emits `JobProgressEvent` via an optional callback. Job subprocesses write NDJSON progress lines on stderr; the executor parses them into `WorkerRuntime`. Bench renders a `rich.Live` dashboard from runtime + `nvidia-smi`/`/proc` probes. Existing `JobProgress.current_step` stays required; optional structured fields enable a later API/frontend without redoing instrumentation.

**Tech Stack:** Python 3, pydantic (`shared/`), `rich.Live`, stdlib `/proc` + `nvidia-smi` CLI, pytest.

**Spec:** `docs/superpowers/specs/2026-07-16-worker-bench-dashboard-progress-design.md`

## Global Constraints

- Do not call Ollama (`ps`/`list`/`tags`/HTTP) from the dashboard refresh path.
- Job subprocess **stdout** remains a single JSON result; progress uses **stderr** NDJSON only.
- Dashboard default: on when stdout is a TTY; off with `--no-dashboard` or `WORKER_BENCH_DASHBOARD=0`.
- Verbose annotation/httpx logs go to a log file when the dashboard is active, not to the Live display.
- Prefer smallest diffs; no fleet/router redesign.
- `docs/` is gitignored — force-add design/plan if committing those files.

## File map

| File | Responsibility |
| --- | --- |
| `shared/worker_contract.py` | Extend `JobProgress`; add `JobProgressEvent` helpers |
| `shared/job_progress.py` (create) | Phase literals, formatters, event builders |
| `autoannotation/autoannotation.py` | Pre-scan sections; emit progress via callback |
| `autoannotation/__main__.py` / `worker/job_main.py` | Wire stderr progress emitter |
| `worker/executor.py` | Parse stderr progress lines; callback to runtime |
| `worker/runtime.py` | Track per-job progress snapshots for dashboard |
| `worker/bench_dashboard.py` (create) | Live UI + hardware probes |
| `worker/hw_probe.py` (create) | nvidia-smi + CPU/RAM parsers |
| `worker/bench.py` | Enable dashboard, log file, CLI flags |
| `tests/test_job_progress.py` (create) | Contract + formatting |
| `tests/test_annotation_progress.py` (create) | Emission / counting |
| `tests/test_executor_progress.py` (create) | stderr parsing |
| `tests/test_hw_probe.py` (create) | Probe parsers |
| `tests/test_bench_dashboard.py` (create) | Render smoke |

---

### Task 1: Shared progress event model

**Files:**
- Create: `shared/job_progress.py`
- Modify: `shared/worker_contract.py`
- Test: `tests/test_job_progress.py`

**Interfaces:**
- Produces: `JobProgressPhase`, `JobProgressEvent`, `format_current_step(event) -> str`, `JobProgress` optional fields

- [ ] **Step 1: Write the failing test**

```python
# tests/test_job_progress.py
from shared.job_progress import JobProgressEvent, format_current_step
from shared.worker_contract import JobProgress


def test_format_current_step_extracting():
    event = JobProgressEvent(
        phase="extracting",
        sections_done=3,
        sections_total=18,
        pass_name="target",
    )
    assert format_current_step(event) == "extracting 3/18 sections (target)"


def test_format_current_step_fetching_unknown_total():
    event = JobProgressEvent(phase="fetching", sections_done=0, sections_total=None)
    assert "fetching" in format_current_step(event)
    assert "?" in format_current_step(event)


def test_job_progress_accepts_structured_fields():
    payload = JobProgress(
        current_step="extracting 1/2 sections (target)",
        phase="extracting",
        sections_done=1,
        sections_total=2,
        pass_name="target",
    )
    assert payload.sections_done == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_job_progress.py -v`  
Expected: FAIL (import / model missing)

- [ ] **Step 3: Write minimal implementation**

Create `shared/job_progress.py`:

```python
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

JobProgressPhase = Literal[
    "fetching",
    "extracting",
    "aggregating",
    "ortholog_fetching",
    "ortholog_extracting",
    "ortholog_aggregating",
    "finalizing",
]

PassName = Literal["target", "ortholog"]


class JobProgressEvent(BaseModel):
    job_id: str | None = None
    phase: JobProgressPhase
    sections_done: int = Field(default=0, ge=0)
    sections_total: int | None = Field(default=None, ge=0)
    papers_done: int | None = Field(default=None, ge=0)
    papers_total: int | None = Field(default=None, ge=0)
    pass_name: PassName | None = None
    message: str | None = None


def format_current_step(event: JobProgressEvent) -> str:
    if event.message:
        return event.message
    total = event.sections_total if event.sections_total is not None else "?"
    base = f"{event.phase} {event.sections_done}/{total} sections"
    if event.pass_name:
        return f"{base} ({event.pass_name})"
    return base
```

Extend `JobProgress` in `shared/worker_contract.py`:

```python
class JobProgress(BaseModel):
    current_step: str = Field(min_length=1)
    phase: str | None = None
    sections_done: int | None = Field(default=None, ge=0)
    sections_total: int | None = Field(default=None, ge=0)
    papers_done: int | None = Field(default=None, ge=0)
    papers_total: int | None = Field(default=None, ge=0)
    pass_name: str | None = None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_job_progress.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add shared/job_progress.py shared/worker_contract.py tests/test_job_progress.py
git commit -m "$(cat <<'EOF'
Add reusable JobProgressEvent and structured JobProgress fields.

EOF
)"
```

---

### Task 2: Section pre-scan helper + progress emissions in annotation pass

**Files:**
- Modify: `autoannotation/autoannotation.py`
- Test: `tests/test_annotation_progress.py`

**Interfaces:**
- Consumes: `JobProgressEvent` from `shared.job_progress`
- Produces: `run_paper_annotation_pass(..., progress_cb=None)`, `get_gene_annotation(..., progress_cb=None)`  
  `progress_cb: Callable[[JobProgressEvent], None] | None`  
  Helper: `collect_paper_sections(paper_manager, pmc_id) -> list[tuple[str, str]]`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_annotation_progress.py
from shared.job_progress import JobProgressEvent


def test_collect_paper_sections_counts_available_parts(monkeypatch):
    from autoannotation import autoannotation as aa

    class FakePM:
        def get_abstract(self, pmc_id):
            return "abs"

        def get_results(self, pmc_id):
            return "res"

        def get_discussion(self, pmc_id):
            return "res"  # same as results → excluded

    sections = aa.collect_paper_sections(FakePM(), "1")
    assert [label for label, _ in sections] == ["abstract", "results"]


def test_run_paper_annotation_pass_emits_fetch_then_extract_totals(monkeypatch):
    # Monkeypatch paper_manager + llm_handler heavily so no network/LLM.
    # Assert progress_cb receives:
    # 1) phase fetching or extracting with sections_total set before any LLM
    # 2) sections_done increments after consensus
    ...
```

Implement the second test with the smallest fakes that exercise: selection → pre-scan → one section → consensus callback. Follow patterns in `tests/test_autoannotation_relevance.py` / existing autoannotation tests for stubbing.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_annotation_progress.py -v`  
Expected: FAIL (`collect_paper_sections` missing)

- [ ] **Step 3: Implement helper + wire `progress_cb`**

In `autoannotation/autoannotation.py`:

1. Add `collect_paper_sections(paper_manager, pmc_id)` extracting the existing abstract/results/discussion logic.
2. In `run_paper_annotation_pass`, after `papers_to_analyze` is known:
   - emit `JobProgressEvent(phase=..., sections_done=0, sections_total=None, pass_name=...)` for fetching if not already emitted by caller
   - build `papers_sections = [(pmc_id, collect_paper_sections(...)) for pmc_id in papers_to_analyze]`
   - `sections_total = sum(len(s) for _, s in papers_sections)`
   - emit extracting with totals
3. Replace inner section-building with the prebuilt list; after each successful consensus, increment and emit.
4. Before aggregate call, emit aggregating phase.
5. Thread `progress_cb` through `get_gene_annotation` for target + ortholog passes (ortholog phases use `ortholog_*` names / `pass_name="ortholog"`).

Keep default `progress_cb=None` (no-op) so CLI/tests unchanged.

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_annotation_progress.py tests/test_autoannotation_relevance.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add autoannotation/autoannotation.py tests/test_annotation_progress.py
git commit -m "$(cat <<'EOF'
Emit structured section progress from paper annotation passes.

EOF
)"
```

---

### Task 3: Subprocess stderr NDJSON progress transport

**Files:**
- Modify: `worker/job_main.py`
- Modify: `worker/executor.py`
- Modify: `autoannotation/__main__.py` (if `main()` needs `progress_cb`)
- Test: `tests/test_executor_progress.py`

**Interfaces:**
- Produces: `PROGRESS_LINE_PREFIX` or JSON object with `"type":"progress"`  
  `executor._run_subprocess(..., on_progress=None)` parses stderr lines  
  `parse_progress_stderr_line(line: str) -> JobProgressEvent | None`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_executor_progress.py
from worker.executor import parse_progress_stderr_line


def test_parse_progress_stderr_line_valid():
    line = '{"type":"progress","phase":"extracting","sections_done":1,"sections_total":4,"pass_name":"target"}'
    event = parse_progress_stderr_line(line)
    assert event is not None
    assert event.sections_done == 1


def test_parse_progress_stderr_line_ignores_noise():
    assert parse_progress_stderr_line("I | Starting annotation") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_executor_progress.py::test_parse_progress_stderr_line_valid -v`  
Expected: FAIL

- [ ] **Step 3: Implement parser + emitter + executor streaming**

1. Add `parse_progress_stderr_line` in `worker/executor.py` (or `worker/progress_io.py` if file is getting large).
2. In `worker/job_main.py` / `autoannotation.__main__`, when `ANNOTATION_JOB_ID` is set, pass `progress_cb` that writes one JSON object per line to stderr: `{"type":"progress", **event.model_dump(exclude_none=True)}`.
3. Change `_run_subprocess` to stream stderr (always, or when `on_progress` provided):
   - read line-by-line
   - if progress → `on_progress(event)`
   - else accumulate for failure logs / optional log sink
   - stdout still collected for final JSON
4. Default capture behavior for non-progress lines: when parent provides a log handler, write there; else discard or keep prior `WORKER_JOB_CAPTURE_STDERR` semantics for failures.

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_executor_progress.py tests/test_worker_bench.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add worker/job_main.py worker/executor.py autoannotation/__main__.py tests/test_executor_progress.py
git commit -m "$(cat <<'EOF'
Pipe annotation progress events over job stderr NDJSON.

EOF
)"
```

---

### Task 4: Runtime tracks live progress snapshots

**Files:**
- Modify: `worker/runtime.py`
- Test: `tests/test_worker_agent.py` or create `tests/test_worker_runtime_progress.py`

**Interfaces:**
- Produces: `ActiveJob.progress: JobProgressEvent | None`  
  `WorkerRuntime.progress_snapshot() -> dict` with active jobs, completed, failed counts  
  `on_progress` wired into execute path

- [ ] **Step 1: Write the failing test**

```python
def test_runtime_stores_progress_for_active_job():
    # Start a fake long-running job future; call runtime._on_job_progress(job_id, event)
    # Assert active snapshot includes phase/sections
    ...
```

- [ ] **Step 2: Run test to verify it fails**

- [ ] **Step 3: Implement**

- Extend `ActiveJob` with `progress: JobProgressEvent | None = None`, `locus: str | None = None`.
- On start, set locus from request.
- Pass `on_progress` into executor that updates `self._active_jobs[job_id].progress`.
- Track `jobs_completed` / `jobs_failed` counters for dashboard (increment in `_reap_finished`).
- Add `snapshot()` method returning a thread-safe copy of dashboard state.

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_worker_runtime_progress.py tests/test_worker_bench.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add worker/runtime.py tests/test_worker_runtime_progress.py
git commit -m "$(cat <<'EOF'
Track per-job progress snapshots on WorkerRuntime.

EOF
)"
```

---

### Task 5: Hardware probe helpers (no Ollama)

**Files:**
- Create: `worker/hw_probe.py`
- Test: `tests/test_hw_probe.py`

**Interfaces:**
- Produces: `probe_gpus() -> list[GpuStat] | GpuUnavailable`  
  `probe_cpu_ram() -> CpuRamStat`  
  `probe_ollama_cpu_percent() -> float | None`

- [ ] **Step 1: Write the failing test**

```python
from worker.hw_probe import parse_nvidia_smi_csv, parse_meminfo, GpuUnavailable


def test_parse_nvidia_smi_csv():
    raw = "0, NVIDIA A100-SXM4-80GB, 72, 61234, 81920, 64\n"
    gpus = parse_nvidia_smi_csv(raw)
    assert gpus[0].index == 0
    assert gpus[0].util_percent == 72
    assert gpus[0].mem_used_mb == 61234


def test_parse_nvidia_smi_empty_is_unavailable():
    assert isinstance(parse_nvidia_smi_csv(""), GpuUnavailable) or parse_nvidia_smi_csv("") == []
    # Prefer explicit GpuUnavailable from probe_gpus() when command missing


def test_parse_meminfo():
    raw = "MemTotal:       503316480 kB\nMemAvailable:   102400000 kB\n"
    stat = parse_meminfo(raw)
    assert stat.total_bytes > stat.available_bytes
```

- [ ] **Step 2: Run test to verify it fails**

- [ ] **Step 3: Implement `worker/hw_probe.py`**

- `nvidia-smi` query as in the spec; catch `FileNotFoundError` / non-zero / empty → `GpuUnavailable(reason=...)`.
- CPU percent via two `/proc/stat` samples (allow caller to pass previous sample for 1s refresh).
- RAM via `/proc/meminfo`.
- Ollama CPU: scan `/proc/[pid]/comm` and `stat` for names containing `ollama`; sum utime/stime deltas (document approximation). Skip if too hard in v1 — optional field `None`.

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_hw_probe.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add worker/hw_probe.py tests/test_hw_probe.py
git commit -m "$(cat <<'EOF'
Add nvidia-smi and /proc hardware probes for bench dashboard.

EOF
)"
```

---

### Task 6: Bench dashboard renderer

**Files:**
- Create: `worker/bench_dashboard.py`
- Test: `tests/test_bench_dashboard.py`

**Interfaces:**
- Produces: `BenchDashboard` with `render(snapshot, hw) -> str` (pure) and `run_live(runtime, stop_event, refresh_sec=1.0)` using `rich.Live`

- [ ] **Step 1: Write the failing test**

```python
from worker.bench_dashboard import render_dashboard


def test_render_dashboard_includes_batch_and_gpu_unavailable():
    text = render_dashboard(
        snapshot={
            "jobs_done": 5,
            "jobs_total": 100,
            "jobs_failed": 1,
            "active": [
                {
                    "job_id": "bench-001",
                    "locus": "TcCLB.1",
                    "elapsed_s": 12.0,
                    "progress": {
                        "phase": "extracting",
                        "sections_done": 2,
                        "sections_total": 9,
                        "pass_name": "target",
                    },
                }
            ],
        },
        hw={"gpus": None, "gpu_error": "nvidia-smi not found", "cpu_percent": 10.0, "ram": "1/16 GB"},
        meta={"fleet": "2x2", "elapsed_s": 60.0},
        spinner_frame="⠋",
    )
    assert "5/100" in text
    assert "1 failed" in text or "failed" in text.lower()
    assert "bench-001" in text
    assert "2/9" in text
    assert "nvidia-smi not found" in text
```

- [ ] **Step 2: Run test to verify it fails**

- [ ] **Step 3: Implement renderer + Live loop**

Match the ASCII layout from the design spec. Spinner cycles over a fixed frames list. `run_live` must not raise if probe fails.

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_bench_dashboard.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add worker/bench_dashboard.py tests/test_bench_dashboard.py
git commit -m "$(cat <<'EOF'
Add rich-friendly bench dashboard renderer.

EOF
)"
```

---

### Task 7: Wire dashboard + log file into `worker bench`

**Files:**
- Modify: `worker/bench.py`
- Modify: `deploy/docker/worker-bench-entrypoint.sh` only if needed for default log path
- Test: extend `tests/test_worker_bench.py` (mock dashboard / assert logging config helpers)

**Interfaces:**
- Consumes: Tasks 4–6
- Produces: CLI `--no-dashboard`, `--log-file`, env `WORKER_BENCH_DASHBOARD`, `WORKER_LOG_FILE`

- [ ] **Step 1: Write the failing test for logging helper**

```python
def test_configure_bench_logging_to_file(tmp_path):
    from worker.bench import configure_bench_logging
    log_path = tmp_path / "worker.log"
    configure_bench_logging(log_file=log_path, dashboard=True)
    import logging
    logging.getLogger("autoannotation").info("hello-file")
    assert "hello-file" in log_path.read_text()
```

- [ ] **Step 2: Run test to verify it fails**

- [ ] **Step 3: Wire `main()`**

1. Resolve `dashboard = sys.stdout.isatty() and not args.no_dashboard and env != 0`.
2. Default log file: `<report_dir>/worker-bench.log` or `<output-dir>/../worker-bench.log`.
3. When dashboard: `configure_bench_logging(file)`, start dashboard thread after runtime starts, stop in `finally`.
4. When not dashboard: keep current `_progress` prints; still allow `--log-file`.
5. During setup (pull/warm), either briefly use plain `_progress` before Live starts, or show a “setup” panel — prefer plain setup lines, then switch to Live when jobs start (simplest).

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_worker_bench.py tests/test_bench_dashboard.py tests/test_job_progress.py -v`  
Expected: PASS

- [ ] **Step 5: Manual smoke (local, optional GPU)**

```bash
python -m worker bench --jobs /path/to/tiny.jsonl --output-dir /tmp/gaa-out --report /tmp/gaa-report.json --slots 1
# TTY: dashboard redraws; log file has DEBUG/INFO noise
python -m worker bench ... --no-dashboard
# linear logs as today
```

- [ ] **Step 6: Commit**

```bash
git add worker/bench.py tests/test_worker_bench.py
git commit -m "$(cat <<'EOF'
Enable live bench dashboard with file-backed logging.

EOF
)"
```

---

### Task 8: Docs touch-up + self-check

**Files:**
- Modify: `worker/README.md` (short dashboard / log-file / progress section)
- Modify: `docs/deploy-worker-bench-hpc.md` (one note: use `--no-dashboard` under sbatch if logs must be linear)

- [ ] **Step 1: Document flags and log path**
- [ ] **Step 2: Run full relevant suite**

Run: `pytest tests/test_job_progress.py tests/test_annotation_progress.py tests/test_executor_progress.py tests/test_hw_probe.py tests/test_bench_dashboard.py tests/test_worker_bench.py tests/test_worker_runtime_progress.py -v`

- [ ] **Step 3: Commit docs** (force-add under `docs/` if needed)

```bash
git add worker/README.md
git add -f docs/deploy-worker-bench-hpc.md docs/superpowers/specs/2026-07-16-worker-bench-dashboard-progress-design.md docs/superpowers/plans/2026-07-16-worker-bench-dashboard-progress.md
git commit -m "$(cat <<'EOF'
Document bench dashboard and structured job progress.

EOF
)"
```

---

## Spec coverage check

| Spec requirement | Task |
| --- | --- |
| Reusable `JobProgressEvent` + extend `JobProgress` | 1 |
| Section totals before LLM; increment after consensus | 2 |
| Ortholog phases / pass_name | 2 |
| stderr NDJSON; stdout JSON intact | 3 |
| Runtime snapshots for active jobs | 4 |
| nvidia-smi + CPU/RAM; no Ollama probes | 5 |
| In-place dashboard; spinner; batch counts | 6–7 |
| Logs to file when dashboard on | 7 |
| Non-TTY / `--no-dashboard` fallback | 7 |
| API/frontend wiring | Deferred (contract ready in Task 1) |

## Out of scope (follow-ups)

- Coordinator `mark_step` persistence of structured fields / frontend progress bar.
- True per-paper progress UI beyond sections.
- Apptainer-specific TTY quirks beyond `--no-dashboard`.
