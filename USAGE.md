# Usage

Operator-facing how-to for tools in this repo. Package READMEs cover design details; this file is for day-to-day commands. Flags and defaults below were taken from the current CLI/`argparse` code (not the README).

## Contents

1. [Shared prerequisites](#shared-prerequisites)
2. [autoannotation (CLI annotator)](#autoannotation-cli-annotator)
3. [get_papers](#get_papers)
4. [validate](#validate)
5. [ortholog_lookup](#ortholog_lookup)
6. [compareannotations](#compareannotations)
7. [goresolve](#goresolve-go-term-resolution)
8. [Coordinator](#coordinator)
9. [Worker (`serve` vs `bench`)](#worker-serve-vs-bench)
10. [Frontend](#frontend)
11. [Advanced / scripts](#advanced--scripts)

---

## Shared prerequisites

```bash
cd /path/to/gene-autoannotator
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
# Web stack (coordinator + worker HTTP deps):
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

## Coordinator

FastAPI control plane: job queue, local profiles, worker claim/progress APIs. It does **not** run annotations in-process; workers do.

```bash
cp coordinator.env.example .env   # edit token / public URL / Mongo as needed
uvicorn coordinator.api:app --host 0.0.0.0 --port 8000
# or:
WORKER_API_TOKEN=dev-token uvicorn coordinator.api:app --host 0.0.0.0 --port 8000
```

Health check: `curl http://127.0.0.1:8000/health`

### Key env vars (`coordinator.env.example` → `.env`)

| Variable | Purpose | Default / notes |
|----------|---------|-----------------|
| `WORKER_API_TOKEN` | Bearer token for `/workers/*` and job progress/complete/fail | **If unset, worker endpoints are unauthenticated** |
| `COORDINATOR_PUBLIC_URL` | Advertised URL for workers (`/coordinator-info`) | — |
| `LEASE_SECONDS` | Claim lease before reaper may requeue | `31536000` (365d) |
| `MAX_ATTEMPTS` | Retries before permanent fail | `3` |
| `WORKER_OFFLINE_SECONDS` | Heartbeat window for “offline” | `60` |
| `REQUIRED_WORKER_VERSION` | Optional min worker version hint | — |
| `MONGO_URI` | Annotation history writes | optional |
| `PROFILES_DIR` | Local profile JSON | `data/profiles` |
| `OLLAMA_HOST` / model vars | Only relevant if something in this process talks to Ollama | — |

API catalog: `coordinator/README.md`. Job submit returns **503** when no workers have available slots.

---

## Worker (`serve` vs `bench`)

```bash
python -m worker serve …   # claim jobs from coordinator (default if subcommand omitted)
python -m worker bench …   # local JSONL batch benchmark, then exit
```

`python -m worker` with no subcommand defaults to **serve**. First run may prompt and write `worker.env` (see `worker.env.example`).

### Shared / serve options

These flags exist on the top-level parser and on `serve` (so `python -m worker --token … serve` and `python -m worker serve --token …` both work):

```bash
python -m worker serve \
  --coordinator-url http://127.0.0.1:8000 \
  --token dev-token \
  --memory-gb 24
```

| Flag | Purpose | Notes |
|------|---------|-------|
| `--coordinator-url` | Coordinator base URL | Else `COORDINATOR_URL` / `worker.env` |
| `--token` | `WORKER_API_TOKEN` | Else env / `worker.env` |
| `--memory-gb` | Model memory budget (GB) for Ollama weights/KV | Sets `WORKER_MODEL_MEMORY_BUDGET_GB`; else env / `worker.env`. `-1` or omit = use machine cap. Does **not** set job slots. |
| `--no-dashboard` | Disable live TTY dashboard | Dashboard is on when stdout is a TTY |

With the dashboard on, verbose worker logs go to `worker-serve.log` (or `--log-file` / `WORKER_LOG_FILE`). Managed `ollama serve` stdout/stderr is teed to `ollama-server-<port>.log` next to that log file (else cwd), and the dashboard **OLLAMA** strip shows process status plus a parsed summary (phase, last `/api/chat`, alerts such as prompt truncation). Offline: `python -m worker.fleet.diagnose_ollama_log ollama-server-11434.log`.

Managed fleet sets `OLLAMA_CONTEXT_LENGTH` to **`OLLAMA_NUM_PARALLEL × OLLAMA_FLEET_SLOT_CTX`** (default slot **8192**) so each parallel slot keeps a full prompt window. Ollama splits total context across parallel slots; without this, `parallel=2` and `-c 8192` yields ~4096/slot and truncates ~6k-token extraction prompts. Larger context may spill weights/KV to system RAM when VRAM is tight (slower, but jobs should complete). Override total with `OLLAMA_CONTEXT_LENGTH`, or per-slot with `OLLAMA_FLEET_SLOT_CTX`.

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
| `--keep-alive` | Ollama `keep_alive` for LLM calls | `5m` if stack fits, else `0` |
| `--no-warm-models` | Deprecated no-op (pre-warm always skipped) | — |
| `--configure-fleet` | Prompt for Ollama fleet settings | off |
| `--no-dashboard` | Linear logs instead of TTY dashboard | off |
| `--log-file` | Verbose log path | under `--output-dir` when dashboard active (survives Docker `--rm`) |

Model residency is two-tier only (no router cache, no pre-warm):

- **All models fit** (`warm_stack`): `OLLAMA_MAX_LOADED_MODELS` = model count, `keep_alive=5m`, load on demand.
- **Otherwise** (`swap` / `vram_overflow`): `MAX_LOADED=1`, load on demand (switches evict; keep_alive is irrelevant).

### Worker env (`worker.env.example`)

`worker.env` is the source of truth: keys you set are not silently overwritten on restart (except one-time migration from legacy names). Model memory budget and job slots are **separate** knobs.

| Variable | Purpose |
|----------|---------|
| `COORDINATOR_URL` | Coordinator base URL |
| `WORKER_API_TOKEN` | Auth token |
| `WORKER_MODEL_MEMORY_BUDGET_GB` | Cap for model weights / KV / Ollama memory (GB). `-1` or omit = machine-derived max. Influences fleet **recommendations** and feasibility warnings; does **not** derive `WORKER_MAX_SLOTS`. |
| `WORKER_MAX_SLOTS` | Concurrent annotation subprocess cap (from fleet setup prompt or manual edit) |
| `OLLAMA_FLEET_SERVERS` / `OLLAMA_FLEET_PARALLEL` | Homogeneous Ollama fleet shape |
| `OLLAMA_FLEET_KEEP_ALIVE` | Written from memory tier when absent; bench/serve apply tier policy (`5m` vs `0`) unless `--keep-alive` is set. |
| `WORKER_DASHBOARD_OLLAMA_PS` | `1` (default) = dashboard IN MEM sizes from `/api/ps`; `0` = in-flight dots only (no HTTP). |
| `WORKER_DASHBOARD_OLLAMA_PS_INTERVAL_SEC` | Min seconds between `/api/ps` probes (default `5`). UI refresh stays faster; in-flight overlays every frame. |
| `ANNOTATION_MEMORY_BUDGET_GB` | **Legacy alias** — read once and migrated to `WORKER_MODEL_MEMORY_BUDGET_GB` on persist |
| `JOB_MEMORY_ESTIMATE_GB` / `WORKER_MEMORY_HEADROOM_GB` | Legacy fallback slot math when fleet keys are absent |
| `WORKER_CACHE_DIR` / `WORKER_OUTPUT_DIR` | Cache / output overrides |
| `OLLAMA_HOST` / `OLLAMA_CHAT_TIMEOUT_SEC` / `OLLAMA_ROUTER_READ_TIMEOUT_SEC` | Ollama / router timeouts (`unset` = unlimited) |
| `OLLAMA_FLEET_SLOT_CTX` | Per-parallel-slot context tokens (default `8192`); total = slot × `OLLAMA_FLEET_PARALLEL` |
| `OLLAMA_CONTEXT_LENGTH` | Total runner context override (wins over slot×parallel) |

Design / fleet details: `worker/README.md`.

---

## Frontend

Next.js UI for jobs, profiles, and Mongo-backed annotation search/review.

```bash
cd frontend
cp .env.example .env.local   # set BACKEND_API_BASE_URL / MONGO_URI
npm install
npm run dev                  # http://localhost:3000 (binds 0.0.0.0)
```

Browser calls go through same-origin `/api/backend` → FastAPI. Point `BACKEND_API_BASE_URL` at the coordinator if it is not on `127.0.0.1:8000`. Set `MONGO_URI` in `.env.local` for annotation search/review (server-side only).

### npm scripts

| Script | Command | Purpose |
|--------|---------|---------|
| `npm run dev` | `next dev --hostname 0.0.0.0` | Dev server |
| `npm run build` | `next build` | Production build |
| `npm run start` | `next start --hostname 0.0.0.0` | Serve production build |
| `npm run lint` | `eslint` | Lint |
| `npm run test` | `node --test` | Lightweight tests |

Pages: `/` usage, `/jobs` queue, `/profiles` local profiles, `/annotations` Mongo search/review. More: `frontend/README.md`.

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

Samples host memory while a real coordinator job runs (sizing aid).

```bash
python scripts/profile_job_memory.py \
  --coordinator-url http://127.0.0.1:8000 \
  --token "$WORKER_API_TOKEN" \
  --profile mtb-h37rv \
  --locus Rv1734c
```

| Flag | Purpose | Default |
|------|---------|---------|
| `--coordinator-url` | Coordinator URL | `http://127.0.0.1:8000` |
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
