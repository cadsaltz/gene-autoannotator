# Worker Bench Protocol

Standard protocol for comparing Ollama fleet configurations on a single machine.
Each run produces a JSON report with **`jobs_per_hour`** as the primary KPI.

## Primary KPI

**`jobs_per_hour`** — completed jobs divided by batch makespan, scaled to one hour.

```json
"primary_kpi": "jobs_per_hour",
"batch": {
  "jobs_completed": 6,
  "makespan_sec": 1842.5,
  "jobs_per_hour": 11.7
}
```

Higher is better. Failed jobs are excluded from the rate; a non-zero
`jobs_failed` count should be investigated before comparing runs.

## Cold cache requirement

Every benchmark run **must** use `--cache cold` unless you are explicitly
testing warm-cache behavior.

Cold cache:

1. Deletes `WORKER_CACHE_DIR/llm_cache` and `WORKER_CACHE_DIR/llm_responses`
   before the batch starts.
2. Sets `AUTOANNOTATION_OLLAMA_KEEP_ALIVE=5m` (unless already overridden) so
   models stay loaded across calls within a job but the LLM response cache is empty.

Warm cache (`--cache warm`) reuses prior caches and is useful for debugging, not
for cross-configuration comparisons.

## Scenario matrix

Run every applicable scenario on a machine and record `jobs_per_hour`. Scenarios
are labeled by fleet shape (servers × parallel per server = aggregation lanes)
and job count.

### Series A — 2×1 lanes (2 servers, 1 parallel each)

| ID | Fleet | Jobs | `--slots` | Notes |
| --- | --- | --- | --- | --- |
| A1 | 2×1 (2 lanes) | 2 | 2 | Baseline; no queue pressure |
| A2 | 2×1 (2 lanes) | 4 | 2 | 2× oversubscription |
| A3 | 2×1 (2 lanes) | 6 | 2 | 3× oversubscription |

### Series B — 2×2 lanes (2 servers, 2 parallel each)

| ID | Fleet | Jobs | `--slots` | Notes |
| --- | --- | --- | --- | --- |
| B1 | 2×2 (4 lanes) | 2 | 4 | Baseline; lanes underutilized |
| B2 | 2×2 (4 lanes) | 4 | 4 | Full lane utilization |
| B3 | 2×2 (4 lanes) | 6 | 4 | Mild oversubscription |
| B4 | 2×2 (4 lanes) | 8 | 4 | 2× oversubscription |

Skip scenarios your hardware cannot support (sizing will reject infeasible
fleets). Document skipped scenarios in your results.

### Job files

Create one JSONL file per job count. Each line is an `AnnotationJobRequest`:

```jsonl
{"profile":"mtb-h37rv","locus":"Rv0001","allow_online_name_lookup":false}
{"profile":"mtb-h37rv","locus":"Rv0002","allow_online_name_lookup":false}
```

Use distinct loci (or profiles) per line. A fixture with 2 jobs lives at
`tests/fixtures/bench_jobs_2.jsonl`; extend it for 4/6/8-job scenarios.

## How to run

### 1. Set fleet configuration

Either let the worker recommend on first run (interactive), or preset in
`worker.env`:

```bash
OLLAMA_FLEET_SERVERS=2
OLLAMA_FLEET_PARALLEL=2
WORKER_MAX_SLOTS=4
```

### 2. Choose model mode

Use a consistent `AUTOANNOTATION_MODEL_MODE` across all scenarios in a study:

```bash
export AUTOANNOTATION_MODEL_MODE=nano   # fast infrastructure testing (~8 GB VRAM)
# export AUTOANNOTATION_MODEL_MODE=lite
# export AUTOANNOTATION_MODEL_MODE=performance
```

### 3. Run a scenario

```bash
AUTOANNOTATION_MODEL_MODE=nano \
python -m worker bench \
  --jobs bench_jobs_6.jsonl \
  --slots 4 \
  --cache cold \
  --report reports/nano_2x2_a3.json
```

| Flag | Required | Purpose |
| --- | --- | --- |
| `--jobs` | yes | JSONL file of job requests |
| `--slots` | no | Override `WORKER_MAX_SLOTS` (match scenario table) |
| `--cache` | no | `cold` (default, required for comparisons) or `warm` |
| `--report` | no | Output path (default: `reports/<timestamp>.json`) |

Exit code is `0` on full success, `1` if any job failed.

### Example: full B-series on a 2×2 machine

```bash
export AUTOANNOTATION_MODEL_MODE=nano

for id jobs slots in B1:2:4 B2:4:4 B3:6:4 B4:8:4; do
  python -m worker bench \
    --jobs "bench_jobs_${jobs}.jsonl" \
    --slots "$slots" \
    --cache cold \
    --report "reports/nano_2x2_${id}.json"
done
```

## Report fields

Top-level structure from `worker.router.metrics.MetricsCollector.build_report()`:

### `primary_kpi`

Always `"jobs_per_hour"`. Documents the comparison metric.

### `batch`

| Field | Meaning |
| --- | --- |
| `jobs_submitted` | Lines read from the JSONL file |
| `jobs_completed` | Jobs that finished without error |
| `jobs_failed` | Jobs that raised an execution error |
| `makespan_sec` | Wall time from first claim to last completion |
| `jobs_per_hour` | **Primary KPI** — `jobs_completed / (makespan_sec / 3600)` |

### `fleet`

| Field | Meaning |
| --- | --- |
| `num_servers` | Ollama server processes launched |
| `parallel` | `OLLAMA_NUM_PARALLEL` per server |
| `lanes` | `num_servers × parallel` (aggregation lane count) |
| `model_mode` | `AUTOANNOTATION_MODEL_MODE` at run time |

### `per_model`

Per-model LLM call statistics. Keys are model names (e.g. `gemma3:1b`).

| Field | Meaning |
| --- | --- |
| `calls` | Total router calls for this model |
| `calls_per_sec` | `calls / makespan_sec` |
| `peak_in_flight` | Maximum concurrent in-flight calls for this model |
| `p50_queue_wait_ms` | Median time waiting for a free lane |
| `p95_queue_wait_ms` | 95th percentile queue wait |
| `p99_queue_wait_ms` | 99th percentile queue wait |

High `p99_queue_wait_ms` with `slots > lanes` indicates oversubscription
stalls. Compare across scenarios to see where adding lanes helps.

Router bench logging (when `log_requests=True`):

| Line prefix | Meaning |
| --- | --- |
| `router dispatch` | Lane acquired; Ollama call starting. `queue=Nms` is time already spent waiting for a free lane (blocking happened before this line). |
| `router chat` | LLM call completed |

Timeline for one request: **wait for that model's lane (silent)** → **`router dispatch`** → Ollama inference → **`router chat`**. With 1 server, `parallel=1`, and 4 models, up to 4 different models can be in flight at once; a second call to the same model waits.

A long gap after `router dispatch` with no matching `router chat` means an
in-flight inference call. A gap with neither line is non-LLM work inside the
annotation subprocess (paper fetch, parse, etc.).

Press **Ctrl+C** once to stop jobs and shut down the Ollama fleet cleanly.
Press **Ctrl+C** again to force exit immediately.

### Oversubscription (`slots > lanes`)

Worker slots control how many annotation **jobs** run in parallel. Router
**lanes** are `servers × parallel × model_count`: each loaded model gets up to
`parallel` concurrent calls per server. Jobs queue only when **their model** is
busy, not when a different model is in use.

LLM HTTP read timeouts are **unlimited by default** (only connect timeout
applies). Inference may take many minutes on large models or CPU/RAM overflow;
Ctrl+C stops the bench. To cap a run, set a finite
`OLLAMA_ROUTER_READ_TIMEOUT_SEC` (seconds); `0` means unlimited.

### `per_job`

Per-job wall time and router stall time. Keys are job IDs (`bench-001`, …).

| Field | Meaning |
| --- | --- |
| `wall_ms` | Total job duration (subprocess wall time) |
| `stall_ms` | Sum of `queue_wait_ms` across all LLM calls in the job |
| `inference_ms` | Sum of model inference time for the job |
| `non_llm_ms` | Remaining wall time (paper fetch, Python, etc.) |

### `per_backend`

Per Ollama server plus a `_fleet` summary. See `busy_lane_sec`, `idle_lane_sec`,
`lane_utilization`, and `_fleet.peak_lane_usage` (burst concurrency).

### `efficiency`

Composite score (0–100) from lane utilization, throughput per lane, memory tier
fit, job success rate, and queue responsiveness. See `components` and `derived`
in the report JSON. Token usage is excluded.

### `token_usage`

Informational LLM token counts from Ollama (`prompt_eval_count` / `eval_count`).
Not used in `efficiency` or `jobs_per_hour`.

| Field | Meaning |
| --- | --- |
| `total` | Batch-wide sums across successful router calls |
| `per_model` | Same fields keyed by model name |
| `calls_with_tokens` | Calls where Ollama returned token counts |

## Recording results

For each scenario, capture at minimum:

| Column | Source |
| --- | --- |
| Scenario ID | A1–B4 |
| `jobs_per_hour` | `batch.jobs_per_hour` |
| `makespan_sec` | `batch.makespan_sec` |
| `jobs_failed` | `batch.jobs_failed` |
| Fleet | `fleet.num_servers` × `fleet.parallel` |
| `model_mode` | `fleet.model_mode` |
| Max `p99_queue_wait_ms` | worst value across `per_model` |

Compare `jobs_per_hour` across scenarios at the same `model_mode` and cache
policy. Expect A3/B4 (oversubscribed) to show higher queue waits and lower
throughput per job than A1/B2 (matched or underutilized lanes).
