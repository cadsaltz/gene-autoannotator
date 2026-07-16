# Deploy worker bench on HPC (Docker + Slurm)

Run performance-mode annotation batches on GPU nodes using a Hub-published Docker image, host-mounted job files, and an example Slurm script.

**Related files:**

| Path | Role |
| --- | --- |
| [`deploy/docker/Dockerfile.worker`](../deploy/docker/Dockerfile.worker) | Lean worker image (`ollama/ollama` base + Python app) |
| [`deploy/scripts/run-worker-bench.sh`](../deploy/scripts/run-worker-bench.sh) | Host wrapper: `docker run --gpus` with bind mounts |
| [`deploy/docker/worker.bench.env.example`](../deploy/docker/worker.bench.env.example) | Env overrides for `--env-file` (fleet, slots, memory) |
| [`deploy/slurm/worker-bench.sbatch`](../deploy/slurm/worker-bench.sbatch) | Example Slurm job |

---

## Three machines

| Role | What it is | What you do there |
| --- | --- | --- |
| **Home laptop** | Where you use Cursor / edit / chat | Push git commits when ready; optional Hub login from browser |
| **Build machine** | Separate host you reach over **SSH**; has Docker | `git pull`, `docker build`, `docker push` |
| **HPC cluster** | Slurm + GPU nodes + Docker | `docker pull`, prepare dirs/JSONL/env, `sbatch` |

You do **not** need Docker on the home laptop for the primary workflow. All build commands below are run **on the build machine after `ssh`**.

---

## Build machine (SSH): build and push

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

---

## HPC cluster: pull, prepare, submit

```bash
ssh you@HPC_LOGIN

# Pull once (or per new TAG)
docker pull DOCKERHUB_USER/gene-autoannotator-worker:TAG

# Shared dirs (adjust to your scratch/project path)
SCRATCH=${SCRATCH:-$HOME/gene-autoannotator-runs}
mkdir -p "$SCRATCH"/{ollama-models,batches,runs,config,logs}
cp /path/to/repo/deploy/docker/worker.bench.env.example "$SCRATCH/config/worker.bench.env"
# Edit fleet/slots if needed: nano "$SCRATCH/config/worker.bench.env"

# Create/upload your batch JSONL to e.g. $SCRATCH/batches/mtb_100.jsonl
# (one AnnotationJobRequest JSON object per line — see below)

# Copy or clone deploy/scripts + deploy/slurm onto the cluster (or clone the repo)
# Edit deploy/slurm/worker-bench.sbatch: partition, gres, image name, paths

export IMAGE=DOCKERHUB_USER/gene-autoannotator-worker:TAG
export SCRATCH="$SCRATCH"

sbatch deploy/slurm/worker-bench.sbatch
squeue -u $USER
# Logs: logs/ or path from #SBATCH --output
```

**Per-run outputs** land under `$SCRATCH/runs/<SLURM_JOB_ID>/` (annotations, report, cache). **Model weights** persist in `$SCRATCH/ollama-models` and are reused across jobs.

---

## Job file format (JSONL)

One `AnnotationJobRequest` JSON object per line. This is **not** the simple one-locus-per-line format from `batch_formats.txt`.

```json
{"profile":"mtb-h37rv","locus":"Rv0001","allow_online_name_lookup":false}
```

Example 100-gene file: `$SCRATCH/batches/mtb_100.jsonl` with one such object per gene/locus.

Common fields: `profile`, `locus`, `allow_online_name_lookup`. Profiles such as `mtb-h37rv` are built into the image; coordinator `data/profiles/` JSON is not required for bench when using known profile IDs.

---

## Model weights (`--models-dir`)

Model weights are **not** baked into the image. Mount a host directory with `--models-dir` (in Slurm: `$SCRATCH/ollama-models`). On the **first** run, the worker auto-pulls missing Ollama models into that directory via existing `ensure_models()` logic. Later runs reuse the same directory — no re-pull unless models change.

Size the models directory for your performance fleet (tens of GB). Ensure compute nodes have outbound HTTPS for first-time pulls and PMC/NCBI access during annotation.

---

## Rebuild vs remount

| Change | Action |
| --- | --- |
| New job JSONL, output paths, cache dir, env overrides (`worker.bench.env`) | **Remount only** — edit host paths or env file; `sbatch` again with same image |
| Fleet size, slots, memory budget, cache mode | **Remount** — edit `worker.bench.env` or wrapper flags; no image rebuild |
| Application code (`worker/`, `autoannotation/`, `shared/`) | **Rebuild** image, push new `TAG`, `docker pull` on HPC |
| Python dependencies (`requirements.txt`) | **Rebuild** |
| Ollama base pin in `Dockerfile.worker` | **Rebuild** |

**Rule of thumb:** rebuild only when code, Python deps, or the Ollama base pin change. Everything else (jobs, paths, fleet tuning, env) is host-mounted or passed at `docker run` time.

---

## Slurm script notes

Edit [`deploy/slurm/worker-bench.sbatch`](../deploy/slurm/worker-bench.sbatch) for your site:

- `#SBATCH --partition=REPLACE_ME` — your GPU partition name
- `#SBATCH --gres=gpu:1` — adjust if your site uses different GPU syntax
- `IMAGE` / `SCRATCH` — set via environment or edit defaults in the script
- Uncomment `module load docker` if your cluster requires it

The script invokes `deploy/scripts/run-worker-bench.sh`, which runs `docker run --rm --gpus …` with read-only jobs, writable outputs/cache, and the shared models directory.

**Dashboard vs Slurm logs:** batch jobs usually have no TTY, so the live bench
dashboard is off and stdout is linear. If you run with a pseudo-TTY or need
guaranteed linear `#SBATCH --output` logs, pass `--no-dashboard` through the
wrapper (append to the `python -m worker bench …` args in
`run-worker-bench.sh` or the sbatch script). Verbose debug logs still land in
`worker-bench.log` under the run directory when `--log-file` is set or the
dashboard would have been active.
