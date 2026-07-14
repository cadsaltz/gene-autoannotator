# Worker Bench Docker + Slurm Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a Hub-publishable worker-bench Docker image, headless bench bootstrap fixes, a host wrapper script, and an example Slurm `sbatch` so performance-mode batches can run on the HPC GPU nodes without reimaging for each job file.

**Architecture:** Lean image `FROM ollama/ollama:<pin>` plus Python app code; model weights and job/output paths bind-mounted at runtime; `run-worker-bench.sh` wraps `docker run --gpus`; Slurm only allocates resources and invokes the wrapper.

**Tech Stack:** Docker, Ollama official image, Python 3, Bash, Slurm `sbatch`, Docker Hub (or compatible registry).

**Spec:** `docs/superpowers/specs/2026-07-14-worker-bench-docker-slurm-design.md`

---

## Three machines (read this first)

| Role | What it is | What you do there |
| --- | --- | --- |
| **Home laptop** | Where you use Cursor / edit / chat | Push git commits when ready; optional Hub login from browser |
| **Build machine** | Separate host you reach over **SSH**; has Docker | `git pull`, `docker build`, `docker push` |
| **HPC cluster** | Slurm + GPU nodes + Docker | `docker pull`, prepare dirs/JSONL/env, `sbatch` |

You do **not** need Docker on the home laptop for the primary workflow. All build commands below are run **on the build machine after `ssh`**.

### Exact steps on the build machine (SSH)

Replace placeholders: `BUILD_HOST`, `DOCKERHUB_USER`, `TAG` (e.g. `20260714` or `latest`).

```bash
# --- From home laptop ---
ssh you@BUILD_HOST

# --- On build machine ---
# 1. Prerequisites (once): Docker Engine, enough disk (~20GB+ free for build layers),
#    network access to Docker Hub and (if private) your git remote.
docker version
git --version

# 2. Get this repo onto the build machine (once, then pull on updates)
git clone <YOUR_GIT_REMOTE_URL> gene-autoannotator
cd gene-autoannotator
# OR if already cloned:
git fetch && git checkout <branch-with-deploy-files> && git pull

# 3. Log in to Docker Hub (once per machine / when token expires)
docker login
# Username: DOCKERHUB_USER
# Password: Hub access token (preferred) or password

# 4. Build the worker image (repo root = context)
docker build \
  -f deploy/docker/Dockerfile.worker \
  -t DOCKERHUB_USER/gene-autoannotator-worker:TAG \
  .

# 5. Push to Hub so the HPC can pull
docker push DOCKERHUB_USER/gene-autoannotator-worker:TAG

# Optional: also tag latest
docker tag DOCKERHUB_USER/gene-autoannotator-worker:TAG \
  DOCKERHUB_USER/gene-autoannotator-worker:latest
docker push DOCKERHUB_USER/gene-autoannotator-worker:latest
```

Smoke-test on the build machine **only if it has an NVIDIA GPU + nvidia-container-toolkit**. If it is CPU-only, skip local GPU smoke and test on the HPC after pull.

```bash
# On build machine (GPU optional smoke) — after implementation exists
mkdir -p /tmp/gaa-smoke/{models,out,cache}
printf '%s\n' \
  '{"profile":"mtb-h37rv","locus":"Rv0001","allow_online_name_lookup":false}' \
  > /tmp/gaa-smoke/jobs.jsonl
cp deploy/docker/worker.bench.env.example /tmp/gaa-smoke/worker.bench.env

deploy/scripts/run-worker-bench.sh \
  --jobs /tmp/gaa-smoke/jobs.jsonl \
  --output-dir /tmp/gaa-smoke/out \
  --report /tmp/gaa-smoke/report.json \
  --models-dir /tmp/gaa-smoke/models \
  --cache-dir /tmp/gaa-smoke/cache \
  --env-file /tmp/gaa-smoke/worker.bench.env \
  --image DOCKERHUB_USER/gene-autoannotator-worker:TAG \
  --cache warm \
  --slots 1
```

### Exact steps on the HPC (after image is on Hub)

```bash
ssh you@HPC_LOGIN

# Pull once (or per new TAG)
docker pull DOCKERHUB_USER/gene-autoannotator-worker:TAG

# Shared dirs (adjust to your scratch/project path)
SCRATCH=${SCRATCH:-$HOME/gene-autoannotator-runs}
mkdir -p "$SCRATCH"/{ollama-models,batches,runs,config,logs}
cp /path/to/repo/deploy/docker/worker.bench.env.example "$SCRATCH/config/worker.bench.env"
# Edit fleet/slots if needed: nano "$SCRATCH/config/worker.bench.env"

# Create/upload your 100-gene JSONL to e.g. $SCRATCH/batches/mtb_100.jsonl
# (one AnnotationJobRequest JSON object per line)

# Copy or clone deploy/scripts + deploy/slurm onto the cluster (or clone the repo)
# Edit deploy/slurm/worker-bench.sbatch: partition, gres, image name, paths

sbatch deploy/slurm/worker-bench.sbatch
squeue -u $USER
# Logs: logs/ or path from #SBATCH --output
```

---

## File structure (to create/modify)

| Path | Responsibility |
| --- | --- |
| `worker/bootstrap.py` | Add `require_coordinator=False` path with inert defaults; no stdin prompts when non-interactive |
| `worker/bench.py` | Call bootstrap with `require_coordinator=False`; set writable `WORKER_ENV_FILE` if unset |
| `tests/test_worker_bootstrap.py` | Tests for headless bench defaults |
| `tests/test_worker_bench.py` | Assert bench passes `require_coordinator=False` (extend existing configure-fleet capture test pattern) |
| `deploy/docker/Dockerfile.worker` | Ollama base + Python + app + entrypoint |
| `deploy/docker/worker-bench-entrypoint.sh` | Validate mounts; exec `python -m worker bench` |
| `deploy/docker/worker.bench.env.example` | Documented env overrides for `--env-file` |
| `deploy/scripts/run-worker-bench.sh` | Host CLI → `docker run` with binds |
| `deploy/slurm/worker-bench.sbatch` | Example Slurm job |
| `docs/deploy-worker-bench-hpc.md` | Operator doc: three-machine workflow (force-add; `docs/` is gitignored) |

---

### Task 1: Headless bench bootstrap (no coordinator prompts)

**Files:**
- Modify: `worker/bootstrap.py`
- Modify: `worker/bench.py`
- Test: `tests/test_worker_bootstrap.py`
- Test: `tests/test_worker_bench.py`

- [ ] **Step 1: Write the failing test for bench bootstrap defaults**

Add to `tests/test_worker_bootstrap.py`:

```python
def test_ensure_worker_env_without_coordinator_uses_defaults(tmp_path, monkeypatch):
    env_path = tmp_path / "worker.env"
    monkeypatch.setattr(bootstrap, "default_env_path", lambda: env_path)
    monkeypatch.delenv("COORDINATOR_URL", raising=False)
    monkeypatch.delenv("WORKER_API_TOKEN", raising=False)
    monkeypatch.delenv("ANNOTATION_MEMORY_BUDGET_GB", raising=False)
    monkeypatch.setattr(bootstrap, "ensure_model_mode", lambda **kwargs: "performance")
    monkeypatch.setattr(
        bootstrap.fleet_setup,
        "ensure_fleet_config",
        lambda **kwargs: None,
    )

    def _should_not_prompt(*_a, **_k):
        raise AssertionError("prompt should not run when require_coordinator=False")

    monkeypatch.setattr(bootstrap, "_prompt_coordinator_url", _should_not_prompt)
    monkeypatch.setattr(bootstrap, "_prompt_token", _should_not_prompt)
    monkeypatch.setattr(bootstrap, "prompt_memory_budget_gb", _should_not_prompt)

    bootstrap.ensure_worker_env(
        interactive=False,
        require_coordinator=False,
        skip_fleet_config=True,
    )

    assert os.environ["COORDINATOR_URL"] == "http://127.0.0.1:9"
    assert os.environ["WORKER_API_TOKEN"] == "unused"
    assert os.environ["ANNOTATION_MEMORY_BUDGET_GB"] == "64"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_worker_bootstrap.py::test_ensure_worker_env_without_coordinator_uses_defaults -v`  
Expected: FAIL (`require_coordinator` unexpected keyword or prompts/missing)

- [ ] **Step 3: Implement `require_coordinator` in bootstrap**

In `worker/bootstrap.py`, extend `ensure_worker_env`:

```python
def ensure_worker_env(
    *,
    cli_overrides: dict | None = None,
    interactive: bool | None = None,
    skip_fleet_config: bool = False,
    require_coordinator: bool = True,
) -> None:
    cli_overrides = cli_overrides or {}
    path = default_env_path()
    is_interactive = sys.stdin.isatty() if interactive is None else interactive

    coord_default = None if require_coordinator else "http://127.0.0.1:9"
    token_default = None if require_coordinator else "unused"
    mem_default = None if require_coordinator else "64"

    url, _ = resolve_value(
        "COORDINATOR_URL",
        env_file=path,
        cli_value=cli_overrides.get("COORDINATOR_URL"),
        prompt_fn=(lambda _k, _d: _prompt_coordinator_url()) if is_interactive and require_coordinator else None,
        default=coord_default,
    )
    token, _ = resolve_value(
        "WORKER_API_TOKEN",
        env_file=path,
        cli_value=cli_overrides.get("WORKER_API_TOKEN"),
        prompt_fn=(lambda _k, _d: _prompt_token()) if is_interactive and require_coordinator else None,
        default=token_default,
    )

    mem = cli_overrides.get("ANNOTATION_MEMORY_BUDGET_GB")
    if mem is not None:
        mem_str = _format_memory_gb(float(mem))
        saved = load_env_file(path)
        saved["ANNOTATION_MEMORY_BUDGET_GB"] = mem_str
        save_env_file(path, saved)
    else:
        mem_str, _ = resolve_value(
            "ANNOTATION_MEMORY_BUDGET_GB",
            env_file=path,
            cli_value=None,
            prompt_fn=(
                (lambda _k, _d: _format_memory_gb(prompt_memory_budget_gb()))
                if is_interactive and require_coordinator
                else None
            ),
            default=mem_default,
        )

    os.environ.setdefault("COORDINATOR_URL", url)
    os.environ.setdefault("WORKER_API_TOKEN", token)
    os.environ.setdefault("ANNOTATION_MEMORY_BUDGET_GB", mem_str)

    ensure_model_mode(env_path=path, interactive=is_interactive)
    if not skip_fleet_config:
        fleet_setup.ensure_fleet_config(interactive=is_interactive, env_path=path)
```

Serve mode keeps `require_coordinator=True` (default).

- [ ] **Step 4: Wire bench to skip coordinator + writable env file**

In `worker/bench.py` `main()`, before `ensure_worker_env`:

```python
    if not os.environ.get("WORKER_ENV_FILE"):
        out_root = os.environ.get("WORKER_OUTPUT_DIR") or "/tmp"
        os.environ["WORKER_ENV_FILE"] = str(Path(out_root) / "worker.env")
```

Change the call to:

```python
    ensure_worker_env(
        interactive=False,
        skip_fleet_config=configure_fleet,
        require_coordinator=False,
    )
```

Update `tests/test_worker_bench.py` `test_bench_configure_fleet_prompts_interactively` expected kwargs to include `require_coordinator=False`.

- [ ] **Step 5: Run bootstrap + bench unit tests**

Run: `pytest tests/test_worker_bootstrap.py tests/test_worker_bench.py -v`  
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add worker/bootstrap.py worker/bench.py tests/test_worker_bootstrap.py tests/test_worker_bench.py
git commit -m "fix: allow headless worker bench without coordinator prompts"
```

---

### Task 2: Dockerfile.worker + entrypoint + env example

**Files:**
- Create: `deploy/docker/Dockerfile.worker`
- Create: `deploy/docker/worker-bench-entrypoint.sh`
- Create: `deploy/docker/worker.bench.env.example`

- [ ] **Step 1: Create `worker.bench.env.example`**

```bash
# Optional overrides for: docker run --env-file ...
# Image already sets sensible performance / single-GPU defaults.

AUTOANNOTATION_MODEL_MODE=performance
OLLAMA_FLEET_SERVERS=1
OLLAMA_FLEET_PARALLEL=1
WORKER_MAX_SLOTS=2
ANNOTATION_MEMORY_BUDGET_GB=64

# Uncomment to fail fast on hung chat (not recommended for performance overnight runs):
# OLLAMA_CHAT_TIMEOUT_SEC=3600
```

- [ ] **Step 2: Create `worker-bench-entrypoint.sh`**

```bash
#!/usr/bin/env bash
set -euo pipefail

JOBS_PATH="${JOBS_PATH:-/jobs/batch.jsonl}"
OUTPUT_DIR="${WORKER_OUTPUT_DIR:-/out/annotations}"
REPORT_PATH="${REPORT_PATH:-/out/reports/report.json}"
CACHE_DIR="${WORKER_CACHE_DIR:-/out/cache}"
MODELS_DIR="${OLLAMA_MODELS:-/models}"
CACHE_MODE="${CACHE_MODE:-cold}"

if [[ ! -f "$JOBS_PATH" ]]; then
  echo "error: jobs file not found at $JOBS_PATH (bind-mount your JSONL)" >&2
  exit 2
fi
mkdir -p "$OUTPUT_DIR" "$(dirname "$REPORT_PATH")" "$CACHE_DIR" "$MODELS_DIR"

if [[ "${REQUIRE_GPU:-1}" == "1" ]] && ! command -v nvidia-smi >/dev/null 2>&1; then
  echo "error: nvidia-smi not found; refuse to run performance bench without GPU (set REQUIRE_GPU=0 to override)" >&2
  exit 2
fi

export OLLAMA_MODELS="$MODELS_DIR"
export WORKER_CACHE_DIR="$CACHE_DIR"
export WORKER_OUTPUT_DIR="$OUTPUT_DIR"
export WORKER_ENV_FILE="${WORKER_ENV_FILE:-$OUTPUT_DIR/worker.env}"

ARGS=(bench --jobs "$JOBS_PATH" --output-dir "$OUTPUT_DIR" --report "$REPORT_PATH" --cache "$CACHE_MODE")
if [[ -n "${WORKER_BENCH_SLOTS:-}" ]]; then
  ARGS+=(--slots "$WORKER_BENCH_SLOTS")
fi

# Allow passthrough args after "--" from docker run
if [[ "${1:-}" == "bench" ]] || [[ "${1:-}" == --* ]]; then
  exec python -m worker "$@"
fi
exec python -m worker "${ARGS[@]}" "$@"
```

Make executable: `chmod +x deploy/docker/worker-bench-entrypoint.sh`

- [ ] **Step 3: Create `Dockerfile.worker`**

Pin matches known POC base; bump deliberately later:

```dockerfile
FROM ollama/ollama:0.15.6

RUN apt-get update \
  && apt-get install -y --no-install-recommends \
       python3 python3-pip python-is-python3 \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt requirements-web.txt ./
RUN python -m pip install --no-cache-dir --break-system-packages \
      -r requirements.txt -r requirements-web.txt

COPY autoannotation/ autoannotation/
COPY worker/ worker/
COPY shared/ shared/
COPY deploy/docker/worker-bench-entrypoint.sh /usr/local/bin/worker-bench-entrypoint.sh
RUN chmod +x /usr/local/bin/worker-bench-entrypoint.sh

ENV AUTOANNOTATION_MODEL_MODE=performance \
    OLLAMA_MODELS=/models \
    WORKER_CACHE_DIR=/out/cache \
    WORKER_OUTPUT_DIR=/out/annotations \
    COORDINATOR_URL=http://127.0.0.1:9 \
    WORKER_API_TOKEN=unused \
    ANNOTATION_MEMORY_BUDGET_GB=64 \
    OLLAMA_FLEET_SERVERS=1 \
    OLLAMA_FLEET_PARALLEL=1 \
    WORKER_MAX_SLOTS=2 \
    PYTHONUNBUFFERED=1

ENTRYPOINT ["/usr/local/bin/worker-bench-entrypoint.sh"]
```

Note: official `ollama/ollama` entrypoint normally starts `ollama serve`. Our ENTRYPOINT replaces that; the worker parent starts `ollama serve` itself via fleet setup. Verify during first build/smoke that `ollama` remains on `PATH`.

- [ ] **Step 4: Commit**

```bash
git add deploy/docker/Dockerfile.worker deploy/docker/worker-bench-entrypoint.sh deploy/docker/worker.bench.env.example
git commit -m "add lean worker-bench Docker image based on ollama"
```

---

### Task 3: Host wrapper `run-worker-bench.sh`

**Files:**
- Create: `deploy/scripts/run-worker-bench.sh`

- [ ] **Step 1: Write the wrapper**

Implement a Bash script that:

- Parses: `--jobs`, `--output-dir`, `--report`, `--models-dir` (required); `--cache-dir`, `--env-file`, `--image`, `--slots`, `--cache`, `--gpus`, `--dry-run` (optional)
- Defaults: `IMAGE=${IMAGE:-gene-autoannotator-worker:latest}`, `GPUS=${GPUS:-'"device=0"'}`, `CACHE=cold`
- `mkdir -p` output, report parent, cache, models
- Absolute-path resolves all host paths
- Builds `docker run --rm --gpus "$GPUS"` with binds:
  - `$JOBS:/jobs/batch.jsonl:ro`
  - `$OUTPUT_DIR:/out/annotations`
  - `$(dirname REPORT):/out/reports`
  - `$CACHE_DIR:/out/cache`
  - `$MODELS_DIR:/models`
- Passes `--env-file` when set
- Sets `-e WORKER_BENCH_SLOTS` when `--slots` given, `-e CACHE_MODE`, `-e REPORT_PATH=/out/reports/$(basename REPORT)`, `-e OLLAMA_MODELS=/models`
- If `--dry-run`, print the docker command and exit 0
- `chmod +x`

- [ ] **Step 2: Shell syntax check**

Run: `bash -n deploy/scripts/run-worker-bench.sh`  
Expected: no output, exit 0

- [ ] **Step 3: Commit**

```bash
git add deploy/scripts/run-worker-bench.sh
git commit -m "add run-worker-bench.sh Docker wrapper for mounted bench runs"
```

---

### Task 4: Example Slurm script + operator doc

**Files:**
- Create: `deploy/slurm/worker-bench.sbatch`
- Create: `docs/deploy-worker-bench-hpc.md` (force-add)

- [ ] **Step 1: Create `deploy/slurm/worker-bench.sbatch`**

```bash
#!/bin/bash
#SBATCH --job-name=gaa-bench
#SBATCH --partition=REPLACE_ME
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=16
#SBATCH --mem=64G
#SBATCH --time=48:00:00
#SBATCH --output=logs/%x-%j.out

set -euo pipefail
mkdir -p logs

# Optional: module load docker  # if required on this site

IMAGE="${IMAGE:-DOCKERHUB_USER/gene-autoannotator-worker:TAG}"
SCRATCH="${SCRATCH:-$HOME/gene-autoannotator-runs}"
RUN_DIR="$SCRATCH/runs/${SLURM_JOB_ID}"
mkdir -p "$RUN_DIR"

# Prefer repo checkout on shared FS, or copy script to $SCRATCH/bin
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

"${SCRIPT_DIR}/scripts/run-worker-bench.sh" \
  --image "$IMAGE" \
  --jobs "$SCRATCH/batches/mtb_100.jsonl" \
  --output-dir "$RUN_DIR/gen_json" \
  --report "$RUN_DIR/report.json" \
  --models-dir "$SCRATCH/ollama-models" \
  --cache-dir "$RUN_DIR/cache" \
  --env-file "$SCRATCH/config/worker.bench.env" \
  --gpus '"device=0"'
```

- [ ] **Step 2: Write `docs/deploy-worker-bench-hpc.md`**

Include the three-machine table and the exact SSH build / HPC sections from the top of this plan, JSONL format example, and “rebuild vs remount” guidance.

- [ ] **Step 3: Commit (force-add docs file)**

```bash
git add deploy/slurm/worker-bench.sbatch
git add -f docs/deploy-worker-bench-hpc.md
git commit -m "add Slurm example and HPC deploy guide for worker bench"
```

---

### Task 5: Build-machine verification checklist (manual)

Performed on the **build machine over SSH** after Tasks 1–4 are on the branch.

- [ ] **Step 1: Sync code on build machine**

```bash
ssh you@BUILD_HOST
cd gene-autoannotator
git pull
```

- [ ] **Step 2: Build and push**

```bash
docker build -f deploy/docker/Dockerfile.worker -t DOCKERHUB_USER/gene-autoannotator-worker:TAG .
docker push DOCKERHUB_USER/gene-autoannotator-worker:TAG
```

Expected: build completes; push uploads layers to Hub.

- [ ] **Step 3: Confirm Hub**

Open `https://hub.docker.com/r/DOCKERHUB_USER/gene-autoannotator-worker` (or `docker pull` on another machine).

- [ ] **Step 4: Commit any pin/doc fixes discovered during build** (only if files change)

---

## Self-review (plan vs spec)

| Spec requirement | Task |
| --- | --- |
| Lean Hub image on `ollama/ollama` | Task 2 |
| External jobs/models/outputs/`--env-file` | Tasks 2–3 |
| Wrapper CLI | Task 3 |
| Example sbatch | Task 4 |
| Headless bootstrap | Task 1 |
| No model bake / no serve mode / no Apptainer / no gene-list converter | Honored (out of scope) |
| Three-machine / SSH build workflow | Plan intro + Task 4/5 + operator doc |

No TBD placeholders in task steps. Types/flag names consistent: `require_coordinator`, `WORKER_BENCH_SLOTS`, `CACHE_MODE`, `REPORT_PATH`.

---

## After implementation

Operator (you): build machine SSH → build/push → HPC pull → edit JSONL/env → `sbatch`. Home laptop only needs git push of this branch to the remote the build machine pulls from.
