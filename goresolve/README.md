# goresolve

Isolated prototype for resolving free-text gene **function** and **functional_category** fields to Gene Ontology (GO) terms. The package lives outside the main annotation pipeline so retrieval, LLM ranking, and consensus can be iterated without touching coordinator, worker, or frontend code.

## Install

From the repository root:

```bash
pip install -r requirements.txt
```

For embedding-based retrieval (default path):

- **sentence-transformers** — installed via `requirements.txt`; first run downloads `sentence-transformers/all-MiniLM-L6-v2` unless you pass `--embed-model`.
- **Ollama** — required for LLM rankers (default model `qwen3:8b`). Pull models before running:

  ```bash
  ollama pull qwen3:8b
  ```

Use `--fake-embeddings` and/or `--exact-only` for offline demos without Ollama or network embedding downloads.

## Download GO ontology

Full GO Basic OBO (~50 MB):

```bash
mkdir -p data
curl -L -o data/go-basic.obo http://purl.obolibrary.org/obo/go/go-basic.obo
```

Or use the helper script from the repo root:

```bash
./scripts/download_go_basic_obo.sh
```

Override the OBO path with `GO_BASIC_OBO_PATH` (default: `data/go-basic.obo`).

## CLI examples

Exact/alias match only (no LLM, offline embeddings) using the test fixture:

```bash
python -m goresolve \
  --obo tests/fixtures/go/mini.obo \
  --category Cytokinesis \
  --fake-embeddings \
  --exact-only
```

Expected: JSON with `"method": "exact_only"` and `GO:0000910` (cytokinesis).

With function text and full pipeline (requires OBO + Ollama):

```bash
python -m goresolve \
  --function "cytokinesis during mitosis" \
  --category Cytokinesis \
  --category Mitosis \
  --obo data/go-basic.obo \
  --model qwen3:8b
```

Read inputs from an annotation JSON file:

```bash
python -m goresolve --from-json path/to/annotation.json --obo data/go-basic.obo
```

Multiple ranker models (wisdom-of-crowds majority):

```bash
python -m goresolve \
  --function "DNA repair" \
  --obo data/go-basic.obo \
  --model qwen3:8b \
  --model llama3.2:3b
```

## Empty input

When both `--function` and all categories are missing or blank, the resolver returns immediately without loading the ontology or calling embedders/LLMs:

```bash
python -m goresolve --obo tests/fixtures/go/mini.obo
```

Expected: `"method": "skipped_no_text"`, empty `go_terms`.

## Python API

```python
from goresolve import resolve_go_terms, has_usable_text
from goresolve.embeddings import SentenceTransformerEmbedder

result = resolve_go_terms(
    function="cytokinesis during mitosis",
    functional_category=["Cytokinesis"],
    ontology_path="data/go-basic.obo",
    embedder=SentenceTransformerEmbedder(),
    ranker_models=["qwen3:8b"],
)
```

## Future annotation hook (not implemented)

When prototyping is validated, wire into `autoannotation.get_gene_annotation` after aggregation:

```python
# Future: after aggregation in autoannotation.get_gene_annotation
import os
from dataclasses import asdict

from goresolve import resolve_go_terms, has_usable_text
from goresolve.embeddings import SentenceTransformerEmbedder

if has_usable_text(annotation.get('function'), annotation.get('functional_category')):
    go_result = resolve_go_terms(
        function=annotation.get('function'),
        functional_category=annotation.get('functional_category'),
        ontology_path=os.environ.get('GO_BASIC_OBO_PATH', 'data/go-basic.obo'),
        embedder=SentenceTransformerEmbedder(),
        ranker_models=os.environ.get('GORESOLVE_MODELS', 'qwen3:8b').split(','),
    )
    annotation['go_terms'] = [asdict(t) for t in go_result.go_terms]
    annotation.setdefault('annotation_metadata', {})['go_resolution'] = {
        'method': go_result.method,
        'queries': list(go_result.queries),
        'shortlist_size': len(go_result.shortlist),
    }
else:
    annotation['go_terms'] = []
```

Persist `go_terms` beside free-text `functional_category`; store shortlist metadata under `annotation_metadata.go_resolution`. Optionally share OBO parsing with `compareannotations` via a shared module later.
