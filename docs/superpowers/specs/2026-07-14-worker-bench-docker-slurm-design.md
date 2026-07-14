# Worker Bench Docker + Slurm Deployment Design

**Date:** 2026-07-14  
**Status:** Approved for implementation planning  
**Scope:** Run `python -m worker bench` on an HPC cluster via Docker + Slurm for performance-mode batches (100+ genes).

## Goals

- Provide a Hub-publishable Docker image for the current worker (fleet + router + bench), modeled after the existing POC pattern ([ethanbustadscri/autoannotator](https://hub.docker.com/r/ethanbustadscri/autoannotator)) but aligned with this repo’s architecture.
- Run real annotation batches (`AUTOANNOTATION_MODEL_MODE=performance`, 100+ genes) on GPU nodes (A100; design for 1 GPU by default).
- Supply job files, outputs, cache, models directory, and env overrides **outside** the image so new batches do not require reimaging.
- Support Docker Hub (or equivalent registry) distribution: build/push locally or in CI; `docker pull` on the cluster.

## Non-goals (first implementation)

- Worker **serve** / coordinator mode on Slurm
- Apptainer/Singularity conversion
- Baking Ollama model weights into the image
- Gene-list → JSONL converter (document JSONL shape only)

## Background (current worker behavior)

Bench mode:

```bash
python -m worker bench \
  --jobs <jsonl> \
  [--slots N] \
  [--cache cold|warm] \
  [--output-dir DIR] \
  [--report PATH] \
  [--keep-alive -1] \
  [--no-warm-models]
```

Startup (both modes): probe hardware → size/load fleet → launch `ollama serve` children → ensure/pull models → start localhost model router → run jobs in subprocesses (`WORKER_MAX_SLOTS`). Jobs talk to the router only (`OLLAMA_ROUTER_URL`). Ollama is intended to run **in the same container** as the worker.

Profiles such as `mtb-h37rv` are built into `autoannotation/organisms.py`; coordinator `data/profiles/` JSON is not required for bench when using known profile IDs.

**Blocker for containers:** `ensure_worker_env()` still resolves `COORDINATOR_URL`, `WORKER_API_TOKEN`, and `ANNOTATION_MEMORY_BUDGET_GB` during bench and can prompt on missing values even when `interactive=False` — fatal for Slurm/non-TTY.

## Approach (chosen)

**Approach 2 — Lean Hub image + external models directory**

- Image contains: Ollama (base), Python, app code (`worker/`, `autoannotation/`, `shared/`), deps, bench entrypoint.
- Model weights live on a host path bind-mounted as `OLLAMA_MODELS`; worker auto-pulls missing models via existing `ensure_models()`.
- Job JSONL, annotation output, report, cache, and optional env file are host paths mounted at run time.

Base image choice (aligned with manager POC): `FROM ollama/ollama:<pinned-version>` then install Python/pip and copy this repo’s packages—not the old monolith scripts.

## Architecture

```text
Hub:  <registry>/gene-autoannotator-worker:<tag>
      (ollama + Python + worker/autoannotation/shared — no jobs, no model weights)

Slurm → run-worker-bench.sh → docker run --gpus … \
  -v $JOBS:/jobs/batch.jsonl:ro \
  -v $OUTPUT_DIR:/out/annotations \
  -v $(dirname $REPORT):/out/reports \
  -v $CACHE_DIR:/out/cache \
  -v $MODELS_DIR:/models \
  [--env-file $ENV_FILE] \
  -e OLLAMA_MODELS=/models \
  …

Container entrypoint → python -m worker bench …
```

### Host-owned paths (persist / vary per run)

| Host input | Container path | Role |
| --- | --- | --- |
| `--jobs` | `/jobs/batch.jsonl` (ro) | Batch of `AnnotationJobRequest` JSON lines |
| `--output-dir` | `/out/annotations` | Annotation JSON outputs |
| `--report` | `/out/reports/<basename>` | Bench metrics report |
| `--cache-dir` | `/out/cache` | PMC / LLM caches (`WORKER_CACHE_DIR`) |
| `--models-dir` | `/models` | Ollama weights (`OLLAMA_MODELS`) |
| `--env-file` | via `docker --env-file` | Overrides image ENV (no rebuild) |

### Image ENV defaults (overridable every run)

```text
AUTOANNOTATION_MODEL_MODE=performance
OLLAMA_MODELS=/models
WORKER_CACHE_DIR=/out/cache
WORKER_OUTPUT_DIR=/out/annotations
COORDINATOR_URL=http://127.0.0.1:9
WORKER_API_TOKEN=unused
ANNOTATION_MEMORY_BUDGET_GB=64
OLLAMA_FLEET_SERVERS=1
OLLAMA_FLEET_PARALLEL=1
WORKER_MAX_SLOTS=2
```

Rebuild only when code, Python deps, or the Ollama base pin change—not when fleet/slots/jobs/paths change.

## Components to add

### 1. `deploy/docker/Dockerfile.worker`

- `FROM ollama/ollama:<pinned>` (pin explicit; bump deliberately)
- Install `python3`, `python3-pip`, `python-is-python3` (or equivalent)
- `WORKDIR` under a dedicated app path
- Copy `requirements.txt` / needed web requirements; `pip install`
- Copy `autoannotation/`, `worker/`, `shared/`
- Do **not** `ollama pull` at build time
- Do **not** `ADD` job lists or large data files
- `ENTRYPOINT` → `deploy/docker/worker-bench-entrypoint.sh`
- Optional non-root user (POC used `hippo`); ensure mounts remain writable

### 2. `deploy/docker/worker-bench-entrypoint.sh`

- Validate required mounts (`/jobs/batch.jsonl`, `/out/annotations`, report parent, `/models`)
- Create cache dir if missing
- Warn/fail if GPU/`nvidia-smi` unavailable for performance (default: require GPU)
- Exec `python -m worker bench` with container paths; honor env for `--slots` / `--cache` if passed as args

### 3. `deploy/docker/worker.bench.env.example`

- Document fleet/slots/model-mode overrides for `--env-file`
- Copy on cluster; edit without touching the image

### 4. `deploy/scripts/run-worker-bench.sh`

Required flags: `--jobs`, `--output-dir`, `--report`, `--models-dir`  
Optional: `--cache-dir`, `--env-file`, `--image`, `--slots`, `--cache`, `--gpus`, `--dry-run`

Creates host dirs; runs `docker run --rm --gpus …` with mounts and env as in Architecture.

### 5. `deploy/slurm/worker-bench.sbatch`

Example `#SBATCH` for 1 GPU, generous wall time (e.g. 48h), CPU/RAM placeholders, calls the wrapper with site-specific partition/module notes.

## Code changes (application)

1. **Headless bench bootstrap** — Do not prompt for coordinator URL/token/memory during bench. Skip serve-only keys or apply inert defaults so non-TTY Docker/Slurm never blocks on stdin.
2. **Fleet** — Non-interactive only on cluster; wrapper/`--env-file` supply `OLLAMA_FLEET_*` and `WORKER_MAX_SLOTS`.
3. **`WORKER_ENV_FILE`** — If the worker persists env, point it at a writable path under `/out` or `/tmp` so the image layer is not required to be writable for that purpose.

Keep existing auto-pull / warm-model behavior.

## Job file format

JSONL, one `AnnotationJobRequest` per line, e.g.:

```json
{"profile":"mtb-h37rv","locus":"Rv0001","allow_online_name_lookup":false}
```

Not the simple one-locus-per-line format from `batch_formats.txt` (converter explicitly out of scope).

## End-to-end workflow

1. **Build/push:** `docker build -f deploy/docker/Dockerfile.worker -t <registry>/gene-autoannotator-worker:<tag> .` then `docker push`
2. **Cluster once:** create `--models-dir`, batches dir, runs dir; copy env example; `docker pull`
3. **Each batch:** write/update JSONL; `sbatch` → wrapper → container; first run fills models dir; later runs reuse it
4. **Collect:** annotations, report JSON, Slurm logs

Assumptions: cluster Docker + NVIDIA Container Toolkit (`docker run --gpus`); compute nodes have outbound HTTPS for NCBI/PMC and first-time model pulls.

## Cluster context (known)

- CPU nodes: 128 cores, 1024 GB RAM  
- GPU nodes: 128 cores, 2048 GB RAM, NVIDIA A100 with **320 GB VRAM** total per node  
- Container runtime: **Docker** (not Apptainer for this design)  
- Exact `#SBATCH --partition` / `--gres` syntax is site-specific; example script uses placeholders and comments

## Success criteria

- [ ] Lean worker image builds and pushes to a registry
- [ ] `run-worker-bench.sh` runs a small JSONL locally (or on cluster) with mounts
- [ ] Bench completes without stdin prompts inside Docker
- [ ] Models land in `--models-dir` and are reused on a second run
- [ ] Example `sbatch` documents GPU request + wrapper invocation
- [ ] README or deploy doc section describes Hub + Slurm workflow

## Risks / notes

- First performance pull + 100-gene batch is wall-time and disk heavy; size `#SBATCH --time` and `--models-dir` disk accordingly.
- Multi-GPU fleet (`OLLAMA_FLEET_SERVERS>1`) is optional later once site GPU request syntax is confirmed; default remains 1×1 fleet.
- Existing Hub POC (~3.4 GB) is a distribution precedent, not a drop-in replacement for current worker code.
