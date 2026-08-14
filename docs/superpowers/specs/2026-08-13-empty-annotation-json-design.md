# Empty annotation JSON for zero-paper jobs

**Date:** 2026-08-13  
**Status:** Approved for implementation planning  
**Scope:** Persist a blank annotation JSON when a job finds no papers to analyze. No LLM calls. Jobs that analyze papers are unchanged.

## Current behavior

`get_gene_annotation` still returns a result dict when retrieval/selection yields nothing: `gene_distillation` and `gene_annotation` are `None`, metadata is built (quality flags include `no_papers_retrieved` / `no_eligible_papers` / `no_papers_analyzed`). No extractor/consensus/aggregation calls run.

`autoannotation/__main__.py` then bails:

```python
if parsed is None:
    if result.get("gene_distillation") is None:
        ...  # "No annotation produced"
        return  # no file
```

The worker/CLI job still completes successfully. Coordinator/Mongo get no annotation document from disk. Ortholog LLM is already skipped when `merged_annotation is None`.

## Goal

Every completed job writes `gen_<id>.json` under the usual output dir. Zero-paper jobs write a schema-shaped annotation with null biology fields and a curator note. Zero extra LLM calls.

## Non-goals

- Changing jobs that analyzed any paper (including LLM-filter failure after papers).
- Forcing an ortholog literature pass when the target had no papers.
- GO ranking on empty text (existing skip remains).

## Design

Handle this only at the persist boundary (`__main__.py`), after `get_gene_annotation` returns.

**Trigger (all of):** `gene_annotation is None`, `gene_distillation is None`, `used_ids` is empty.

**Not triggered:** any job that entered extraction (`used_ids` non-empty). Those keep today’s write-or-skip behavior.

**Blank document:**

- `gene_id` / `name` from resolved target metadata (or submitted identifiers).
- Every profile biology field `null` (`functional_category` null, not `[]`).
- `annotation_notes`: short fixed text that no papers were available and no literature-backed annotation was produced.
- `annotation_metadata`: the dict already on the result (duration, literature zeros, quality flags). Attach `field_coverage` all `insufficient_evidence`.
- Do not add `go_terms`.

Reuse `field_defs.resolve_effective_fields` + existing `build_field_coverage`. Write with the same path convention as successful jobs.

Ortholog: leave `get_gene_annotation` as-is so filling JSON at write time cannot accidentally enable an ortholog LLM pass.
