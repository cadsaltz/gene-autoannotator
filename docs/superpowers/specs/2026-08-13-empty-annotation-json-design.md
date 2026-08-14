# Empty annotation JSON for zero-paper jobs

**Date:** 2026-08-13  
**Status:** Approved for implementation planning  
**Scope:** Always persist annotation JSON. When the target pass analyzes no papers, seed a blank target annotation so the existing ortholog relevance gate can still run. No LLM on a pass that has no papers. Jobs that analyzed target papers are unchanged.

## Current behavior

Target pass with zero papers: no extractor/consensus/aggregation LLM. `gene_distillation` is `None`, `merged_annotation` stays `None`.

Ortholog **would** pass the relevance gate (`cumulative_relevance` is 0.0 < 9.0) if `allow_ortholog_fallback` is on and a hit exists. It **does not run**, because:

```python
if merged_annotation is None or not eligible_fields:
    skipped_reason = 'no_eligible_fields'
```

`__main__.py` then returns without writing JSON.

## Desired behavior

| Target papers | Ortholog papers (if fallback on) | Result |
| --- | --- | --- |
| none | pass not eligible / off / no hit | Blank JSON; notes say no target papers |
| none | none | Blank JSON; notes say no papers on target (and ortholog if it ran) |
| none | some | Blank target fields + ortholog-derived fills as today; notes say no target papers |
| some | (unchanged) | Unchanged |

Ortholog trigger stays **exactly** the existing `_decide_ortholog_action` (fallback flag + cum relevance + hit). Seeding a blank target must not skip that pass.

LLM: none for a pass with `used_ids` empty. Ortholog **may** call LLMs if it has papers (same as any ortholog pass).

## Design

In `get_gene_annotation`, after the target pass, if `gene_distillation is None` and target `used_pmc_ids` is empty:

1. Build blank annotation (`gene_id`/`name`, biology fields `null`, `annotation_notes` about no target papers, existing `annotation_metadata`, `field_coverage` all `insufficient_evidence`).
2. Set `merged_annotation` to that doc **before** `fields_eligible_for_ortholog` and `_decide_ortholog_action`.

Then existing ortholog + merge + `__main__.py` write path apply.

If ortholog runs and also has no distillation, keep the blank doc; append a short notes sentence that the ortholog pass also found no papers. If ortholog fills fields, keep the no-target-papers note and existing ortholog merge notes.

Do **not** seed a blank annotation when target `used_pmc_ids` is non-empty but distillation failed (paper jobs unchanged).

`__main__.py`: if `gene_annotation` is set, write as today. Zero-paper jobs now have `gene_annotation` set so they persist. Leave the “No annotation produced” return only for the paper-but-no-distillation case.
