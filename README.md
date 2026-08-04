# Gene Autoannotator

Work-in-progress tooling for generating literature-backed gene annotation drafts. The project combines a Python annotation pipeline, local file-backed organism profiles, a FastAPI job queue, a Next.js review UI, and comparison scripts for benchmarking generated JSON against trusted annotations.

Generated annotations are curator aids, not curated truth. The pipeline tries to expose evidence, paper selection, unknown fields, and limitations so a human can review the result.

## What It Does

1. Resolve a local saved or custom/ad hoc organism profile.
2. Resolve an annotation target from a supplied gene name, locus, or both.
3. Resolve a gene name from a supplied value, profile table, local cache, NCBI Gene, UniProt, or locus fallback.
4. Query PubMed Central by locus and, when available, gene name.
5. Download/cache PMC XML and extract abstract, results, and discussion text.
6. Score and select papers with organism/gene relevance rules.
7. Ask three Ollama models for section-level JSON summaries.
8. Ask a consensus model to reconcile each section.
9. Filter malformed or wrong-locus JSON.
10. Ask an aggregation model for the final gene-level annotation.
11. Attach metadata about paper selection, quality flags, field coverage, timings, and gene-name provenance.

Main generated fields are `gene_id`, `name`, `function`, `functional_category`, `drug_susc_impact`, `infection_impact`, `essential_in_vitro`, `essential_in_vivo`, `annotation_notes`, and `annotation_metadata`.

## Repo Map

- `autoannotation/`: core Python pipeline, organism profiles, PMC retrieval, LLM prompts, metadata, and CLI.
- `coordinator/`: FastAPI API, SQLite job queue, local JSON organism profiles, optional MongoDB annotation history/search, and in-process runner.
- `frontend/`: Next.js UI for job submission, profile management, queue monitoring, and direct MongoDB annotation search/review.
- `compareannotations/`: trusted-vs-generated scoring tools using exact matching, GO/category graph logic, embeddings/NLI, and an Ollama judge.
- `tests/`: mostly deterministic unit/API tests; some model-style tests require local model dependencies.
- `gen_json/`, `trust_json/`, `test_json/`: generated examples, trusted annotation fixtures, and small comparison fixtures.
- `run_pipeline.py`: manual benchmark script for a fixed MTB gene list; appends scores to `pipeline_scores.jsonl`.
- `get_papers.py`: diagnostic CLI for paper retrieval/ranking without running LLM annotation.

## Dependencies

Runtime assumptions:

- Python 3.11+ recommended.
- Node.js/npm for the frontend.
- Internet access to NCBI Entrez/PubMed Central and optional UniProt lookup.
- Local Ollama with the configured annotation/comparison models pulled.
- SQLite for job queue state.
- MongoDB optional, used by the backend for annotation history writes and by the Next.js server for annotation search/review reads. Organism profiles are local JSON files (`data/profiles` / `PROFILES_DIR`), not MongoDB.

Python install:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-web.txt
pip install pandas cloudscraper
```

The pinned requirement files may need cleanup as the project settles.

Frontend install:

```bash
cd frontend
npm install
cp .env.example .env.local
```

Ollama defaults:

```bash
ollama pull mistral-nemo:12b
ollama pull llama3:8b
ollama pull gemma3:12b
ollama pull phi4:14b
ollama pull qwen2.5:7b-instruct
```

For smaller annotation models:

```bash
export AUTOANNOTATION_MODEL_MODE=lite
ollama pull mistral:7b-instruct
ollama pull llama3.2:3b
ollama pull gemma3:4b
ollama pull phi3:3.8b
```

## Configuration

Useful environment variables:

- `AUTOANNOTATION_MODEL_MODE=performance|lite`
- `AUTOANNOTATION_SUMMARY_MODELS=model1,model2,model3`
- `AUTOANNOTATION_CONSENSUS_MODEL=model`
- `AUTOANNOTATION_AGGREGATION_MODEL=model`
- `AUTOANNOTATION_OLLAMA_KEEP_ALIVE=-1` (or `forever`) keeps models loaded indefinitely; `0` (default outside bench) unloads after each call; `5m` keeps warm for five minutes.
- `OLLAMA_HOST=http://host:11434` when Ollama is not local.
- `MONGO_URI` or `MONGODB_URI` to enable annotation history/search. Set it for the FastAPI backend so completed jobs can be saved, and set it in `frontend/.env.local` so Next.js can read stored annotations directly.
- `PROFILES_DIR=data/profiles` for local organism profile JSON storage (default).
- `COORDINATOR_API_BASE_URL=http://127.0.0.1:8000` for the Next.js proxy/server calls (legacy `BACKEND_API_BASE_URL` still honored as a fallback).
- `CORS_ORIGINS` and `CORS_ORIGIN_REGEX` for FastAPI browser access.
- `GO_BASIC_OBO_PATH=data/go-basic.obo` for richer functional-category comparison.

Local/generated assets:

- `.cache/` stores PMC text, parsed sections, LLM responses, and gene-name cache records.
- `gen_json/` stores generated annotation JSON.
- `coordinator/jobs.sqlite3` stores queued/completed web jobs and is ignored by git.
- `frontend/.env.local` stores Next.js server configuration such as `MONGO_URI` for annotation reads and is ignored by git.
- `Mycobacterium_tuberculosis_H37Rv_txt_v5.txt` is referenced for MTB annotation-table gene names but is not committed.
- `pipeline_scores.jsonl`, `completed_genes.txt`, and `error_log.txt` are local `run_pipeline.py` run artifacts (gitignored).
- `creds/` remains gitignored for any local secrets; it is not required by the benchmark harness.

## Usage

Validate a profile/locus:

```bash
python -m autoannotation.validate --profile mtb-h37rv --locus Rv0001
python -m autoannotation.validate --organism "Trypanosoma cruzi" --strain "CL Brener" --locus TcCLB.503799.4
```

Look up the top KEGG SSDB ortholog for a target gene (same profile/locus resolution as jobs):

```bash
python -m autoannotation.ortholog_lookup --profile mtb-h37rv --locus Rv3407
python -m autoannotation.ortholog_lookup mtb-h37rv Rv3407
```

The profile must define `kegg_organism_code` (e.g. `mtu` for MTB H37Rv). Results are cached under `.cache/orthologs/`.

Annotation targets require a profile or organism plus either a gene name or a
locus. Supplying both improves validation and retrieval; name-only submissions
can proceed when the name becomes the primary identifier or can be resolved to a
locus.

Inspect paper retrieval/ranking:

```bash
python get_papers.py --profile mtb-h37rv --locus Rv0001 --json-out name_query_results.json
```

Generate one annotation from the CLI:

```bash
python -m autoannotation --profile mtb-h37rv --locus Rv0001
python -m autoannotation --profile tcruzi-clbrener --locus TcCLB.503799.4 --name TcUBP1
```

Run the backend (copy `coordinator.env.example` to `.env` first if you need
worker tokens, MongoDB, or other coordinator settings):

```bash
cp coordinator.env.example .env   # optional; edit as needed
uvicorn coordinator.api:app --host 0.0.0.0 --port 8000
```

Run the frontend:

```bash
cd frontend
npm run dev
```

If developing through SSH port forwarding:

```bash
ssh -L 3000:127.0.0.1:3000 -L 8000:127.0.0.1:8000 user@server
```

Compare generated output to trusted JSON:

```bash
python -m compareannotations trust_json/trust_Rv0001.json gen_json/gen_Rv0001.json
```

Run tests:

```bash
pytest
cd frontend && npm test && npm run lint
```

Some comparison/model tests may need HuggingFace model downloads and local Ollama availability.

## Web API Summary

- `GET /health`: job store, annotation store, profile store, queue, and process resource status.
- `GET /profiles`: local organism profiles (`PROFILES_DIR` / `data/profiles`).
- `POST /profiles`, `GET /profiles/{profile_id}`, `PUT /profiles/{profile_id}`, `DELETE /profiles/{profile_id}`: create, read, update, and delete local profile files.
- `POST /validate`: target preflight for a profile or ad hoc organism plus name, locus, or both. It returns the resolved profile, submitted/resolved identifiers, primary identifier, and warnings.
- `POST /jobs`: queue an annotation job after the same target preflight; the stored job request includes `target_preflight`.
- `GET /jobs?order=queue|newest`: list job history and queue summary.
- `DELETE /jobs/history`: clear completed/failed jobs only.
- `GET /jobs/{job_id}` and `/jobs/{job_id}/result`: job metadata/result.
- `GET /annotations/search?query=...`: FastAPI-compatible annotation search endpoint; the frontend now uses its own Next.js `/api/annotations/...` routes for Mongo reads.
- `GET /annotations/{annotation_id}` and `/versions`: FastAPI-compatible current annotation and older version endpoints; the frontend reads the same Mongo documents through Next.js routes.

## Current Limitations

- No authentication, authorization, rate limiting, job cancellation, retries, or queue size limits.
- Jobs run in the FastAPI process; this is not a durable worker system.
- Only one annotation job runs at a time.
- Web progress is coarse (`queued`, `running`, `saving_result`, `completed`, `failed`).
- API request paths such as `cache_dir` and `output_dir` are trusted server paths.
- MongoDB is optional; if unavailable to FastAPI, jobs can complete but completed annotations will not be saved to MongoDB. Profile CRUD uses local files and does not require MongoDB. If MongoDB is unavailable to the Next.js server, annotation search/review will not work even if FastAPI is online.
- Literature parsing handles common top-level PMC/JATS sections and may miss nested or unusual section layouts.
- Relevance scoring is heuristic and should be tuned with `get_papers.py` plus tests.
- LLM validation checks JSON shape and gene identity, not factual correctness.
- Comparison scoring is useful for benchmarking but depends on local ML/Ollama models and can be slow.
- Some local assets and credentials are intentionally not committed.

## Roadmap / WIP

Likely next improvements:

- More precise job progress from the backend, ideally per paper/section/model step.
- Security around the job API, such as auth or a passcode-enforced queue.
- Safer path handling and deployment guidance before exposing the API beyond trusted users.
- Better separation of fast unit tests from model/integration tests.
- Requirement-file cleanup once the runtime dependency set stabilizes.
- Ollama token usage included in metadata
