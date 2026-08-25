# Usage

Operator-facing how-to for tools in this repo. Package READMEs cover design details; this file is for day-to-day commands. Flags and defaults below were taken from the current CLI/`argparse` code (not the README).

## Contents

1. [Web architecture (how the pieces fit)](#web-architecture-how-the-pieces-fit)
2. [Shared prerequisites](#shared-prerequisites)
3. [autoannotation (CLI annotator)](#autoannotation-cli-annotator)
4. [get_papers](#get_papers)
5. [validate](#validate)
6. [ortholog_lookup](#ortholog_lookup)
7. [compareannotations](#compareannotations)
8. [goresolve](#goresolve-go-term-resolution)
9. [Backend (public job queue)](#backend-public-job-queue)
10. [Worker (`serve` / `run` / `bench`)](#worker-serve--run--bench)
11. [Dispatcher + Slurm (HPC)](#dispatcher--slurm-hpc)
12. [Frontend](#frontend)
13. [End-to-end setup recipes](#end-to-end-setup-recipes)
14. [Advanced / scripts](#advanced--scripts)

---

## Web architecture (how the pieces fit)

One **public backend** owns the durable job queue. Compute never receives inbound
connections from the cloud: every worker and the HPC dispatcher **pull** over
HTTPS. Spare laptops and SCRI Slurm allocations compete for the **same** queue
via atomic claim (only one winner per job).

```text
Readers → Frontend → Backend (SQLite queue + worker API + profiles)
                           ↑
              outbound HTTPS only (claim / heartbeat / progress / complete)
                           │
          ┌────────────────┴────────────────┐
          ▼                                 ▼
   laptop `worker serve`            HPC Dispatcher (scrontab)
   (continuous pull)                      │
                                   sbatch worker-run.sbatch
                                          ▼
                                 `worker run --claim-one`
                                 (annotate → complete → exit)
```

| Role | What it is | Where it runs |
|------|------------|---------------|
| **Frontend** | Next.js UI | Public / cloud host |
| **Backend** | FastAPI control plane (formerly “coordinator”) | Cloud host with the frontend |
| **Dispatcher** | Peek queue depth + `sbatch` launcher | SCRI (shared FS + `scrontab`) |
| **Worker serve** | Long-lived claim loop | Spare laptop / always-on box |
| **Worker run** | One-shot claim + annotate + exit | Inside a Slurm GPU allocation |
| **Worker bench** | Local JSONL batch (**no** backend) | Laptop / HPC bench scripts |

**Pull-only:** the backend never dials SCRI or laptops. No port-forward into the
hospital network is required for compute.

**MongoDB** stores completed annotation documents for search/review. It is **not**
the live job queue.

Deeper deploy notes: `docs/deploy-cloud-backend-hpc-dispatcher.md`.  
Design: `docs/superpowers/specs/2026-08-24-cloud-backend-hpc-dispatcher-design.md`.  
Rollback tag (pre-redesign stack): `pre-cloud-hpc-redesign-2026-08-24`.

### How Slurm fits (plain English)

Slurm is a **batch scheduler**. You do not “SSH into a GPU and leave a daemon
running.” You submit a short script with `sbatch`; Slurm finds a free node,
runs the script, then frees the node when the script exits.

In this stack:

1. A user (or the UI) submits a job → it sits **`queued`** on the public backend.
2. Every few minutes, **`python -m dispatcher once`** runs on SCRI (via `scrontab`).
3. The dispatcher asks the backend “how many queued?” (`GET /jobs/queue-summary`).
4. It asks Slurm “how many of *my* `gene-autoannotator-run` jobs are already
   pending/running?” (`squeue`).
5. It submits up to `min(queued, max_inflight - already_inflight)` new allocations
   with `sbatch deploy/slurm/worker-run.sbatch`.
6. Each allocation starts, runs `python -m worker run --claim-one`, which
   **atomically claims** one queued job (or exits 0 if the queue emptied),
   provisions a local Ollama fleet, annotates, reports progress/complete to the
   backend, deregisters, and exits.

The dispatcher does **not** claim jobs and does **not** run annotations. It only
launches workers. Claiming stays on the same API laptop `serve` uses, so both
fleets can run together safely.

---

## Shared prerequisites

```bash
cd /path/to/gene-autoannotator
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
# Web stack (backend + worker + dispatcher HTTP deps):
pip install -r requirements-web.txt
```

Common runtime needs:

- **Ollama** for annotation / goresolve LLM steps (`OLLAMA_HOST` if not local).
- **Internet** for NCBI PMC / optional UniProt / KEGG ortholog lookup.
- **`.cache/`** for PMC text, gene-name cache, ortholog cache.
- **`gen_json/`** default output for CLI annotations.
- **`data/profiles/`** local organism profile JSON (or `PROFILES_DIR`).

Targets need a **profile or organism**, plus a **locus and/or name**. Prefer both when you have them.

Useful shared env vars (annotation models / hosts):

| Variable | Purpose |
|----------|---------|
| `AUTOANNOTATION_MODEL_MODE` | `performance` or `lite` |
| `AUTOANNOTATION_SUMMARY_MODELS` | Comma-separated extractor models |
| `AUTOANNOTATION_CONSENSUS_MODEL` | Consensus model |
| `AUTOANNOTATION_AGGREGATION_MODEL` | Aggregation model |
| `AUTOANNOTATION_SECTION_EXCERPT_MAX_CHARS` | Max characters of paper excerpt per extractor call (default 10000); oversized abstract/results/discussion text is split on paragraphs, then sentences; each chunk gets its own extractors + consensus |
| `AUTOANNOTATION_OLLAMA_KEEP_ALIVE` | e.g. `-1` / `forever`, `0`, `5m` |
| `OLLAMA_HOST` | Ollama base URL |
| `NCBI_API_KEY` | Optional NCBI rate-limit key |
| `GO_BASIC_OBO_PATH` | GO OBO path (goresolve / richer compare) |
| `PROFILES_DIR` | Local profile JSON dir (default `data/profiles`) |

---

## autoannotation (CLI annotator)

Runs the full literature → LLM annotation pipeline for one gene and writes JSON under `--output-dir`.

```bash
python -m autoannotation --profile mtb-h37rv --locus Rv0001
python -m autoannotation --profile tcruzi-clbrener --locus TcCLB.503799.4 --name TcUBP1
python -m autoannotation --organism "Trypanosoma cruzi" --strain "CL Brener" --locus TcCLB.503799.4
# Legacy MTB shorthand (positional locus only):
python -m autoannotation Rv0001
```

### Useful flags

| Flag | Purpose | Default |
|------|---------|---------|
| `gene` (positional) | Legacy MTB locus shorthand | — |
| `--profile` | Saved profile id (e.g. `mtb-h37rv`) | — |
| `--organism` | Species name/synonym (ad hoc profile) | — |
| `--strain` | Strain/isolate with `--organism` | — |
| `--locus` | Gene locus | — |
| `--name` | Gene name/symbol for retrieval + prompts | — |
| `-c` / `--cache-dir` | PMC / paper cache | `./.cache` |
| `--gene-name-cache` | Locus→name cache dir | `.cache/gene_names` |
| `--no-online-name-lookup` | Skip NCBI/UniProt name lookup | off |
| `--refresh-gene-name-cache` | Ignore cached online name records | off |
| `--cache-supplied-name` | Persist `--name` as manual cache record | off |
| `--output-dir` | Annotation JSON output directory | `gen_json` |

---

## get_papers

Fetches and ranks PMC papers for a target **without** running LLM annotation. Use to debug relevance / selection.

```bash
python get_papers.py --profile mtb-h37rv --locus Rv0001
python get_papers.py --profile mtb-h37rv --locus Rv0001 --json-out name_query_results.json
python get_papers.py --profile tcruzi-clbrener --locus TcCLB.503799.4 --name TcUBP1 --top 15
```

### Useful flags

| Flag | Purpose | Default |
|------|---------|---------|
| `gene` (positional) | Legacy locus shorthand | — |
| `--profile` / `--organism` / `--strain` / `--locus` / `--name` | Same target resolution as annotator | — |
| `--cache` | Paper cache directory | `./.cache` |
| `--gene-name-cache` | Locus→name cache | `.cache/gene_names` |
| `--no-online-name-lookup` | Skip online name lookup | off |
| `--refresh-gene-name-cache` | Refresh online name cache | off |
| `--cache-supplied-name` | Persist `--name` into cache | off |
| `--top` | Top ranked papers to print | `10` |
| `--bottom` | Bottom ranked papers to print | `5` |
| `--target-relevance` | Selection cumulative-relevance target | `9.0` |
| `--min-score` | Min paper score for selection | `0.1` |
| `--min-papers` | Min papers to keep | `5` |
| `--max-papers` | Max papers to keep | `20` |
| `--max-rank` | Max rank considered | `20` |
| `--json-out` | Write full ranked relevance JSON | — |

---

## validate

Lightweight profile/locus preflight (same idea as API `POST /validate`).

```bash
python -m autoannotation.validate --profile mtb-h37rv --locus Rv0001
python -m autoannotation.validate mtb-h37rv Rv0001
python -m autoannotation.validate --organism "Trypanosoma cruzi" --strain "CL Brener" --locus TcCLB.503799.4
```

### Useful flags

| Flag | Purpose |
|------|---------|
| `identifier` / `positional_locus` | Shorthand: `PROFILE LOCUS` |
| `--profile` | Saved profile id |
| `--organism` / `--strain` | Ad hoc organism (+ optional strain) |
| `--locus` | Gene locus (required via flag or positional) |

Do not mix positional `identifier` with `--profile`/`--organism`, or `--profile` with `--organism`.

---

## ortholog_lookup

Looks up the top KEGG SSDB ortholog for a target (same profile/locus resolution as jobs). Profile needs `kegg_organism_code`. Results cache under `.cache/orthologs/`.

```bash
python -m autoannotation.ortholog_lookup --profile mtb-h37rv --locus Rv3407
python -m autoannotation.ortholog_lookup mtb-h37rv Rv3407
```

### Useful flags

| Flag | Purpose | Default |
|------|---------|---------|
| `identifier` / `positional_locus` | Shorthand: `PROFILE LOCUS` | — |
| `--profile` / `--organism` / `--strain` / `--locus` | Target resolution | — |
| `-c` / `--cache-dir` | Cache for KEGG SSDB responses | `./.cache` |

Exit code `0` if a top hit was found, `1` otherwise.

---

## compareannotations

Scores a generated annotation JSON against a trusted reference.

```bash
python -m compareannotations trust_json/trust_Rv0001.json gen_json/gen_Rv0001.json
python -m compareannotations -v path/to/trusted.json path/to/generated.json
```

### Useful flags

| Flag | Purpose |
|------|---------|
| `trusted` | Path to trusted JSON |
| `generated` | Path to generated JSON |
| `-v` / `--verbose` | Per-step debug logging |

Needs local ML / optional Ollama for some scorers; set `GO_BASIC_OBO_PATH` for richer functional-category comparison.

---

## goresolve (GO term resolution)

Maps free-text `function` and/or `functional_category` from an annotation to Gene Ontology terms. Use the CLI below for one-off runs, or enable it on annotation jobs via the profile flag described in **Pipeline integration**.

### Pipeline integration (annotation jobs)

GO resolution is **opt-in per organism profile** (`go_resolution_enabled`, default **off**). In the profile editor, enable **Resolve GO terms after aggregation** (runs after target and ortholog aggregation using the job’s summary models; free-text categories are still extracted).

When enabled on a job:

- **Target pass** — after aggregation, resolves `function` / `functional_category` into top-level `go_terms`; provenance in `annotation_metadata.go_resolution`.
- **Ortholog pass** — when an ortholog fallback runs, resolves ortholog text separately into `annotation_metadata.ortholog_go_terms` (target `go_terms` are not overwritten); provenance in `annotation_metadata.ortholog_go_resolution`.
- **Requirements** — workers need `data/go-basic.obo` (or `GO_BASIC_OBO_PATH`) plus Ollama with the job’s summary models available.
- **Soft-fail** — resolver errors do not fail the job; `go_terms` / `ortholog_go_terms` stay empty and metadata records `method: error` with an `error` string.
- **Empty text** — both function and categories empty → `skipped_no_text`, no embedding/LLM work.

When the flag is off, the pipeline skips GO resolution entirely (no `go_terms` keys added).

### One-time setup

```bash
cd /path/to/gene-autoannotator
source .venv/bin/activate   # or your project venv

# Full Gene Ontology (~50 MB) — required for real runs
./scripts/download_go_basic_obo.sh
# writes data/go-basic.obo

# Ollama must be running for LLM ranking (server pin: 0.15.6)
ollama serve
ollama pull qwen3:8b
# optional second model for majority voting:
# ollama pull gemma3:4b
```

First real run also downloads the embedding model `sentence-transformers/all-MiniLM-L6-v2` (unless you use `--fake-embeddings`).

### Real test from a past annotation JSON

`--from-json` reads `function` and `functional_category` from the file:

```bash
python -m goresolve \
  --from-json gen_json/tcruzi-clbrener/gen_TcCLB.503799.4.json \
  --obo data/go-basic.obo \
  --model qwen3:8b
```

Save output:

```bash
python -m goresolve \
  --from-json path/to/annotation.json \
  --obo data/go-basic.obo \
  --model qwen3:8b \
  > /tmp/goresolve_out.json
```

### Paste fields by hand

```bash
python -m goresolve \
  --obo data/go-basic.obo \
  --category Mitosis \
  --category "Cell cycle" \
  --category Cytokinesis \
  --function "involved in mitotic spindle assembling and chromosome segregation" \
  --model qwen3:8b
```

### Multi-model (wisdom-of-crowds)

Pass `--model` more than once. Each model independently picks GO IDs from the **same shortlist**; the resolver keeps IDs that reach majority (`ceil(n/2)`). This mirrors the annotation pipeline’s multi-extractor consensus, applied only to GO ranking.

```bash
python -m goresolve \
  --from-json gen_json/tcruzi-clbrener/gen_TcCLB.503799.4.json \
  --obo data/go-basic.obo \
  --model qwen3:8b \
  --model gemma3:4b
```

Single `--model` is fine for a quick real test. Multi-model is for checking agreement / robustness. If no `--model` is given, the CLI uses `qwen3:8b`.

### Behavior notes

- **`queries`** — PMID/PMC tokens are stripped before retrieval and ranking.
- **Categories** — long category lists are soft-capped so sprawl does not dominate the shortlist.
- **Hierarchy** — after majority voting, a parent GO term may be dropped when a more specific descendant also wins.

### Eval retest

After resolver fixes, re-run the same fixtures used in the Aug 2026 eval (three models, same shortlist):

```bash
python -m goresolve --from-json bench_out/annotations/tcruzi-clbrener/gen_TcCLB.507521.110.json \
  --obo data/go-basic.obo --model qwen3:14b --model gemma3:12b --model mistral-nemo:12b

python -m goresolve --from-json gen_json/gen_Rv3418c.json \
  --obo data/go-basic.obo --model qwen3:14b --model gemma3:12b --model mistral-nemo:12b

python -m goresolve --from-json gen_json/gen_Rv0969.json \
  --obo data/go-basic.obo --model qwen3:14b --model gemma3:12b --model mistral-nemo:12b

python -m goresolve --from-json bench_out/annotations/tcruzi-clbrener/gen_TcCLB.511139.40.json \
  --obo data/go-basic.obo --model qwen3:14b --model gemma3:12b --model mistral-nemo:12b
```

Expected improvements vs prior eval JSON: no PMIDs in `queries`; fewer parent+child pairs in `go_terms`; fewer unsupported exact nouns (e.g. `detoxification` when function is chaperone-only).

### What the JSON output means

| Field | Meaning |
|-------|---------|
| `go_terms` | Final GO terms (id, name, aspect, confidence, method, sources) |
| `method` | e.g. `rag_llm_majority`, `exact_only`, `skipped_no_text`, `no_candidates` |
| `queries` | Text searched (from categories + function) |
| `shortlist` | Candidate GO terms from exact/alias/embedding retrieval (LLM may only pick from these) |
| `votes` | Per-model ID lists before majority merge |

If both `function` and `functional_category` are empty/null → `method: skipped_no_text`, empty `go_terms` (no embedding/LLM work).

### Offline smoke check (not a real GO test)

Uses the tiny fixture ontology; no Ollama / full OBO needed:

```bash
python -m goresolve \
  --obo tests/fixtures/go/mini.obo \
  --category Cytokinesis \
  --fake-embeddings \
  --exact-only
```

### Useful flags

| Flag | Purpose | Default |
|------|---------|---------|
| `--from-json PATH` | Load `function` + `functional_category` from annotation JSON | — |
| `--function TEXT` | Function prose | — |
| `--category TEXT` | Repeatable category labels | — |
| `--obo PATH` | Ontology file | `data/go-basic.obo` or `GO_BASIC_OBO_PATH` |
| `--model NAME` | Repeatable Ollama ranker model(s) | `qwen3:8b` if omitted |
| `--exact-only` | Skip LLM; return exact/alias hits only | off |
| `--fake-embeddings` | Deterministic fake embedder (offline demos) | off |
| `--top-k N` | Max shortlist size | `25` |
| `--min-cosine F` | Embedding similarity floor | `0.35` |
| `--embed-model NAME` | Sentence-transformers model for retrieval | `sentence-transformers/all-MiniLM-L6-v2` |

More design notes: `goresolve/README.md`.

---

## Backend (public job queue)

FastAPI control plane: job queue, local profiles, worker claim/progress APIs.
It does **not** run annotations in-process; workers do.

```bash
cp coordinator.env.example .env   # edit token / public URL / Mongo as needed
uvicorn backend.api:app --host 0.0.0.0 --port 8000
# Legacy entrypoint still works for one release:
# uvicorn coordinator.api:app --host 0.0.0.0 --port 8000
```

Health check: `curl http://127.0.0.1:8000/health`

Compose (frontend + backend):

```bash
docker compose -f deploy/compose/docker-compose.coordinator.yml up -d --build
```

### Key env vars (`coordinator.env.example` → `.env`)

| Variable | Purpose | Default / notes |
|----------|---------|-----------------|
| `WORKER_API_TOKEN` | Bearer token for worker routes + `GET /jobs/queue-summary` | **If unset, those routes are unauthenticated** |
| `BACKEND_PUBLIC_URL` | Advertised public URL (`/coordinator-info` still exists) | prefer over legacy `COORDINATOR_PUBLIC_URL` |
| `WORKER_CAPACITY_REQUIRED` | Reject `POST /jobs` while no worker has a free slot | default **on** for `backend.api:app`; set **`0` for HPC-only** (otherwise dispatcher never starts because nothing can queue) |
| `LEASE_SECONDS` | Claim lease before reaper may requeue; renewed by progress **and** heartbeats | `21600` (6h) |
| `MAX_ATTEMPTS` | Retries before permanent fail | `3` |
| `WORKER_OFFLINE_SECONDS` | Heartbeat window for “offline” | `60` |
| `MONGO_URI` | Annotation history writes | optional |
| `PROFILES_DIR` | Local profile JSON | `data/profiles` |

API catalog: `backend/README.md`. User-facing auth for paper readers is **not**
implemented yet — do not expose the backend widely without a reverse-proxy gate.

---

## Worker (`serve` / `run` / `bench`)

```bash
python -m worker serve …          # continuous pull from backend (laptops)
python -m worker run --claim-one  # one-shot; Slurm allocations use this
python -m worker bench …          # local JSONL batch; no backend
```

`python -m worker` with no subcommand defaults to **serve**. First run may prompt
and write `worker.env` (see `worker.env.example`). Prefer `BACKEND_URL`; legacy
`COORDINATOR_URL` still works.

### serve (spare laptop / always-on)

```bash
BACKEND_URL=https://api.example.org \
WORKER_API_TOKEN=dev-token \
python -m worker serve

# or CLI overrides (also persist into worker.env):
python -m worker serve \
  --coordinator-url http://127.0.0.1:8000 \
  --token dev-token \
  --memory-gb 24
```

| Flag | Purpose | Notes |
|------|---------|-------|
| `--coordinator-url` | Backend base URL | Else `BACKEND_URL` / `COORDINATOR_URL` / `worker.env` |
| `--token` | `WORKER_API_TOKEN` | Else env / `worker.env` |
| `--memory-gb` | Model memory budget (GB) for Ollama weights/KV | Sets `WORKER_MODEL_MEMORY_BUDGET_GB`; does **not** set job slots |
| `--no-dashboard` | Disable live TTY dashboard | Dashboard is on when stdout is a TTY |

With the dashboard on, verbose logs go to `worker-serve.log` (or `WORKER_LOG_FILE`).
Managed `ollama serve` logs tee to `ollama-server-<port>.log`. Offline:
`python -m worker.fleet.diagnose_ollama_log ollama-server-11434.log`.

Managed fleet sets each `ollama serve` child's `OLLAMA_CONTEXT_LENGTH` to
**`OLLAMA_FLEET_SLOT_CTX × OLLAMA_FLEET_PARALLEL`** (default slot **8192**).

### run (Slurm one-shot)

Used by `deploy/slurm/worker-run.sbatch`. Typical flow inside an allocation:

1. Register with an ephemeral name (`max_slots=1`).
2. Claim one job (exit 0 if none left — avoids wasting GPU after a race).
3. Provision local Ollama fleet / router.
4. Annotate; heartbeat + progress keep the lease fresh.
5. `complete` or `fail`; deregister; exit.

```bash
# Manual (same as Slurm body, after env is set):
python -m worker run --claim-one

# Or execute a pre-materialized job file (no claim):
python -m worker run --job-file /path/to/job.json
```

Requires `BACKEND_URL` (or `COORDINATOR_URL`) and usually `WORKER_API_TOKEN`.
`GAA_REPO_ROOT` must be set when launched via the sample sbatch (dispatcher exports it).

### Bench options

```bash
python -m worker bench \
  --jobs tests/fixtures/batch_tcruzi_100.jsonl \
  --slots 2 \
  --cache cold \
  --output-dir gen_json \
  --report reports/bench.json
```

| Flag | Purpose | Default |
|------|---------|---------|
| `--jobs` | **Required.** JSONL of `AnnotationJobRequest` per line | — |
| `--slots` | Concurrent worker slots override | sized / env |
| `--cache` | `cold` or `warm` | `cold` |
| `--report` | Bench report JSON path | `reports/<timestamp>.json` |
| `--output-dir` | Annotation JSON output dir (local disk) | — |
| `--keep-alive` | Ollama `keep_alive` for LLM calls | Uses persisted `OLLAMA_FLEET_KEEP_ALIVE` when omitted |
| `--configure-fleet` | Prompt for Ollama fleet settings | off |
| `--no-dashboard` | Linear logs instead of TTY dashboard | off |
| `--log-file` | Verbose log path | under `--output-dir` when dashboard active |

Model residency uses env-authoritative caps:

- **`OLLAMA_MAX_LOADED_MODELS`** — write-if-missing on first ensure.
- **`OLLAMA_FLEET_KEEP_ALIVE`** — write-if-missing default `0`.

HPC bench (Docker + Slurm, not the dispatcher path): `docs/deploy-worker-bench-hpc.md`.

### Worker env (`worker.env.example`)

`worker.env` at the **repo root** is the source of truth (`WORKER_ENV_FILE`).

| Variable | Purpose |
|----------|---------|
| `BACKEND_URL` | Preferred backend base URL |
| `COORDINATOR_URL` | Legacy alias (still accepted) |
| `WORKER_API_TOKEN` | Auth token |
| `WORKER_MODEL_MEMORY_BUDGET_GB` | Cap for model weights / KV (GB). `-1` / omit = machine max |
| `WORKER_MAX_SLOTS` | Concurrent annotation subprocess cap (`serve` / `bench`) |
| `OLLAMA_FLEET_SERVERS` / `OLLAMA_FLEET_PARALLEL` | Homogeneous Ollama fleet shape |
| `OLLAMA_FLEET_KEEP_ALIVE` | Default `0`; copied to `AUTOANNOTATION_OLLAMA_KEEP_ALIVE` |
| `OLLAMA_MAX_LOADED_MODELS` | Write-if-missing residency cap |
| `WORKER_CACHE_DIR` / `WORKER_OUTPUT_DIR` | Cache / output overrides |

Design / fleet details: `worker/README.md`.

---

## Dispatcher + Slurm (HPC)

The dispatcher is a **short-lived** program: peek → maybe `sbatch` → exit. It is
**not** a second job queue and **not** a long-running coordinator.

```bash
# One manual pass (login node / SCRI host with sbatch+squeue):
export BACKEND_URL=https://api.example.org
export WORKER_API_TOKEN=…          # same token as cloud backend
export DISPATCHER_MAX_INFLIGHT=4
export DISPATCHER_SBATCH_SCRIPT=/path/to/gene-autoannotator/deploy/slurm/worker-run.sbatch
# Also export worker/model env the sbatch job will inherit (--export=ALL):
# AUTOANNOTATION_MODEL_MODE, OLLAMA_*, etc.

python -m dispatcher once
# → prints: Submitted N worker job(s).
```

### What one pass does

1. `GET {BACKEND_URL}/jobs/queue-summary` with bearer token → `queued` count.
2. `squeue --user $USER --name gene-autoannotator-run` → `inflight` count.
3. `to_launch = min(queued, DISPATCHER_MAX_INFLIGHT - inflight)`.
4. For each launch: `sbatch --export=ALL,GAA_REPO_ROOT=<repo> $DISPATCHER_SBATCH_SCRIPT`.

Keep the job name in the sbatch script as **`gene-autoannotator-run`** — that is
how the dispatcher counts in-flight work.

### Customize `deploy/slurm/worker-run.sbatch`

Edit for your site before production:

- `#SBATCH --partition=…` (required; sample has `REPLACE_ME`)
- GPU / CPU / mem / time / account / QoS / modules
- Ensure `python` is the project venv on compute nodes (module load, absolute
  `.venv/bin/python`, or container wrapper)

Body of the sample script (conceptually):

```bash
cd "${GAA_REPO_ROOT:?GAA_REPO_ROOT must be set}"
python -m worker run --claim-one
```

`GAA_REPO_ROOT` is required because Slurm often runs a **spooled copy** of the
script, so `BASH_SOURCE` would point at the spool directory, not the repo.

### scrontab (periodic)

```cron
*/5 * * * * cd /shared/gene-autoannotator && set -a && . ./dispatcher.env && set +a && .venv/bin/python -m dispatcher once >> dispatcher.log 2>&1
```

Keep the interval longer than a typical dispatcher pass so runs do not overlap.
Confirm with your site’s `scrontab` list/edit commands.

### If your lead already has a working Slurm test script

**Yes — use it as the site template.** Our dispatcher is generic (`sbatch` + env).
What usually differs per cluster is the `#SBATCH` header and how Python/Ollama
are activated on the compute node. Workflow:

1. Keep his working `#SBATCH` lines / modules / container invocation.
2. Replace the job body with `cd "$GAA_REPO_ROOT" && python -m worker run --claim-one`
   (or his equivalent that ends in that command).
3. Keep `#SBATCH --job-name=gene-autoannotator-run` (or change `SLURM_JOB_NAME` in
   `dispatcher/loop.py` to match his name — they must agree).
4. Point `DISPATCHER_SBATCH_SCRIPT` at that file and run `python -m dispatcher once`.

If you paste his script into the repo (or a private path), we can adapt the
sample sbatch and dispatcher env to match SCRI exactly.

### Dispatcher env checklist

| Variable | Required | Purpose |
|----------|----------|---------|
| `BACKEND_URL` | yes | Public backend (legacy `COORDINATOR_URL` ok) |
| `WORKER_API_TOKEN` | yes | Same token as backend |
| `DISPATCHER_MAX_INFLIGHT` | yes | Cap concurrent Slurm run jobs for this user |
| `DISPATCHER_SBATCH_SCRIPT` | yes | Absolute path to the sbatch file |

More: `docs/deploy-cloud-backend-hpc-dispatcher.md` §3.

---

## Frontend

Next.js UI for jobs, profiles, fleet health, and Mongo-backed annotation search.

```bash
cd frontend
cp .env.example .env.local   # BACKEND_API_BASE_URL / MONGO_URI
npm install
npm run dev                  # http://localhost:3000 (binds 0.0.0.0)
```

Browser calls go through same-origin `/api/backend` → FastAPI. Prefer
`BACKEND_API_BASE_URL` (legacy `COORDINATOR_API_BASE_URL` still works). Set
`MONGO_URI` in `.env.local` for annotation search/review (server-side only).

### npm scripts

| Script | Command | Purpose |
|--------|---------|---------|
| `npm run dev` | `next dev --hostname 0.0.0.0` | Dev server |
| `npm run build` | `next build` | Production build |
| `npm run start` | `next start --hostname 0.0.0.0` | Serve production build |
| `npm run lint` | `eslint` | Lint |
| `npm run test` | `node --test` | Lightweight tests |

Pages: `/` usage, `/jobs` queue, `/profiles` local profiles, `/annotations` Mongo
search/review. Fleet tiles: backend health + connected workers. More:
`frontend/README.md`.

---

## End-to-end setup recipes

### A. Laptop-only (dev / dual-fleet without Slurm)

```bash
# Terminal 1 — backend
cp coordinator.env.example .env
# set WORKER_API_TOKEN=dev-token ; WORKER_CAPACITY_REQUIRED can stay default
uvicorn backend.api:app --host 0.0.0.0 --port 8000

# Terminal 2 — worker
BACKEND_URL=http://127.0.0.1:8000 WORKER_API_TOKEN=dev-token \
  python -m worker serve

# Terminal 3 — frontend
cd frontend && cp .env.example .env.local && npm run dev
```

Submit a job from `/jobs` or:

```bash
curl -s -X POST http://127.0.0.1:8000/jobs \
  -H 'Content-Type: application/json' \
  -d '{"profile":"mtb-h37rv","locus":"Rv0001","allow_online_name_lookup":false}'
```

### B. Cloud UI + SCRI dispatcher (production shape)

1. **Cloud:** compose frontend+backend; set `WORKER_CAPACITY_REQUIRED=0`,
   `WORKER_API_TOKEN`, `BACKEND_PUBLIC_URL`, `MONGO_URI`, CORS to the public UI.
2. **SCRI:** clone/checkout repo on shared FS; venv; customize
   `deploy/slurm/worker-run.sbatch`; write `dispatcher.env`; run one
   `python -m dispatcher once` by hand; then install `scrontab`.
3. **Optional laptop:** `BACKEND_URL=https://… WORKER_API_TOKEN=… python -m worker serve`.

Verify: job stays `queued` with no workers → next dispatcher pass submits ≤
`DISPATCHER_MAX_INFLIGHT` → Slurm job claims/completes → UI shows progress.

### C. Dispatcher dry-run without real Slurm

```bash
export BACKEND_URL=http://127.0.0.1:8000
export WORKER_API_TOKEN=dev-token
export DISPATCHER_MAX_INFLIGHT=2
export DISPATCHER_SBATCH_SCRIPT=/bin/true   # or a local echo wrapper
# Note: real dispatch_once also calls squeue; unit tests mock both.
python -m dispatcher once
```

For real SCRI validation, prefer a one-line wrapper that logs argv instead of
`/bin/true`, then graduate to the real sbatch file.

---

## Advanced / scripts

### `run_pipeline.py`

Manual MTB benchmark harness: fixed gene list, compare vs trusted JSON, append scores to `pipeline_scores.jsonl`. No credentials or Google client libraries required. Not the normal app entry point.

```bash
python -m run_pipeline 2>&1 | tee log.txt
```

### `python -m worker.job_main`

Internal: run **one** annotation job in an isolated subprocess (used by the worker runtime).

```bash
python -m worker.job_main --request-file /path/to/AnnotationJobRequest.json
```

| Flag | Purpose |
|------|---------|
| `--request-file` | **Required.** Path to JSON `AnnotationJobRequest` |

### `scripts/download_go_basic_obo.sh`

Downloads full GO basic OBO to `data/go-basic.obo`.

```bash
./scripts/download_go_basic_obo.sh
```

### `scripts/profile_job_memory.py`

Samples host memory while a real backend job runs (sizing aid).

```bash
python scripts/profile_job_memory.py \
  --coordinator-url http://127.0.0.1:8000 \
  --token "$WORKER_API_TOKEN" \
  --profile mtb-h37rv \
  --locus Rv1734c
```

| Flag | Purpose | Default |
|------|---------|---------|
| `--coordinator-url` | Backend URL (legacy flag name) | `http://127.0.0.1:8000` |
| `--token` | Worker API token | `$WORKER_API_TOKEN` |
| `--profile` | Profile id | `mtb-h37rv` |
| `--locus` | Gene locus | `Rv1734c` |
| `--interval-sec` | Sample interval | `2.0` |
| `--baseline-sec` | Pre-job baseline window | `10.0` |
| `--safety-factor` | Headroom factor in report | `0.20` |
| `--output-dir` | Report output dir | `.cache/memory_profiles` |
| `--recover-log` | Rebuild report from existing `memory.log` (no new job) | — |
| `--job-id` | Job id when recovering | — |

### `scripts/investigate_ortholog_pipeline.py`

Diagnostic: ortholog vs target PubMed retrieval (no LLM). Hard-coded MTB gene list; run with no args:

```bash
python scripts/investigate_ortholog_pipeline.py
```

### `scripts/ortholog_paper_counts.py`

Lightweight ortholog vs target raw PMC hit counts (hits NCBI). Optional positional loci; default MTB set if none given:

```bash
python scripts/ortholog_paper_counts.py
python scripts/ortholog_paper_counts.py Rv0001 Rv3407
```
