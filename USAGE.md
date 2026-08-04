# Usage

Operator-facing how-to for tools in this repo. Package READMEs cover design details; this file is for day-to-day commands.

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

# Ollama must be running for LLM ranking
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

Single `--model` is fine for a quick real test. Multi-model is for checking agreement / robustness.

### Behavior notes

- **`queries`** — PMID/PMC tokens are stripped before retrieval and ranking.
- **Categories** — long category lists are soft-capped so sprawl does not dominate the shortlist.
- **Hierarchy** — after majority voting, a parent GO term may be dropped when a more specific descendant also wins.

### Eval retest

After resolver fixes, re-run the same fixtures used in the Aug 2026 eval (three models, same shortlist):

```bash
# After fixes, re-run the same fixtures used in Aug 2026 eval:
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

| Flag | Purpose |
|------|---------|
| `--from-json PATH` | Load `function` + `functional_category` from annotation JSON |
| `--function TEXT` | Function prose |
| `--category TEXT` | Repeatable category labels |
| `--obo PATH` | Ontology file (default `data/go-basic.obo` or `GO_BASIC_OBO_PATH`) |
| `--model NAME` | Repeatable Ollama ranker model(s); default `qwen3:8b` |
| `--exact-only` | Skip LLM; return exact/alias hits only |
| `--fake-embeddings` | Deterministic fake embedder (offline demos) |
| `--top-k N` | Max shortlist size (default 25) |
| `--min-cosine F` | Embedding similarity floor (default 0.35) |

More design notes: `goresolve/README.md`.
