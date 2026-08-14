# Empty Annotation JSON Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Spec:** `docs/superpowers/specs/2026-08-13-empty-annotation-json-design.md`

**Goal:** Persist JSON for every zero-paper target job; seed a blank target annotation so the existing ortholog relevance gate can still run.

**Architecture:** After a target pass with no analyzed papers, build a null-field annotation and assign `merged_annotation` before ortholog decision. Ortholog LLM runs only if that pass has papers. `__main__.py` writes when `gene_annotation` is set.

**Tech Stack:** Python 3, pytest, `autoannotation/autoannotation.py`, `autoannotation/metadata.py`.

## Global Constraints

- Seed blank target only when target `used_pmc_ids` is empty and `gene_distillation is None`.
- Do not change jobs that analyzed any target paper.
- Ortholog still uses `_decide_ortholog_action` (fallback + cum relevance + hit).
- No LLM on a pass with no papers; ortholog with papers uses the existing pass.
- `annotation_notes` records no target papers; if ortholog also has no papers, mention that too.
- TDD; named git paths only.

## File map

| Path | Action | Responsibility |
|------|--------|----------------|
| `autoannotation/metadata.py` | Modify | `empty_annotation_from_metadata`; notes constants |
| `autoannotation/autoannotation.py` | Modify | Seed blank target before ortholog; append ortholog-no-papers note |
| `tests/test_empty_annotation_json.py` | Create | Helper + seed-before-ortholog + persist |

---

### Task 1: Seed blank target annotation when no papers analyzed

**Files:**
- Modify: `autoannotation/metadata.py`
- Modify: `autoannotation/autoannotation.py`
- Create: `tests/test_empty_annotation_json.py`

**Interfaces:**
- `EMPTY_TARGET_NOTES = 'No papers were available for this gene; no literature-backed target annotation was produced.'`
- `EMPTY_ORTHOLOG_NOTES = 'The ortholog pass also found no papers.'`
- `empty_annotation_from_metadata(annotation_metadata, *, gene_id, name, profile) -> dict`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_empty_annotation_json.py
from autoannotation import metadata
from autoannotation.organisms import resolve_profile


def test_empty_annotation_null_fields_and_notes():
    profile = resolve_profile("mtb-h37rv")
    meta = {"profile_id": "mtb-h37rv", "quality_flags": ["no_papers_analyzed"]}
    doc = metadata.empty_annotation_from_metadata(
        meta, gene_id="Rv9999", name="fake", profile=profile,
    )
    assert doc["gene_id"] == "Rv9999"
    assert doc["function"] is None
    assert doc["functional_category"] is None
    assert doc["annotation_notes"] == metadata.EMPTY_TARGET_NOTES
    assert doc["annotation_metadata"]["field_coverage"]["function"] == "insufficient_evidence"


def test_get_gene_annotation_seeds_blank_when_target_has_no_papers(monkeypatch):
    import autoannotation.autoannotation as aa

    class FakePass:
        gene_distillation = None
        ranked_papers = []
        selection = type("S", (), {
            "selected_records": [],
            "selection_mode": "all_eligible_limited_literature",
            "eligible_count": 0,
        })()
        used_pmc_ids = []
        pmids_analyzed = []
        sections_analyzed = 0
        cumulative_relevance = 0.0

    monkeypatch.setattr(aa, "run_paper_annotation_pass", lambda *a, **k: FakePass())
    monkeypatch.setattr(
        aa, "_decide_ortholog_action",
        lambda **k: aa.OrthologDecision(hit=None, skipped_reason="fallback_disabled_for_job"),
    )
    result = aa.get_gene_annotation(
        profile="mtb-h37rv", locus="Rv9999",
        allow_online_name_lookup=False, allow_ortholog_fallback=False,
    )
    assert result["gene_annotation"] is not None
    assert result["gene_annotation"]["function"] is None
    assert result["used_ids"] == []


def test_blank_target_still_requests_ortholog_when_relevance_is_zero(monkeypatch):
    import autoannotation.autoannotation as aa
    seen = {}

    class FakePass:
        gene_distillation = None
        ranked_papers = []
        selection = type("S", (), {
            "selected_records": [],
            "selection_mode": "all_eligible_limited_literature",
            "eligible_count": 0,
        })()
        used_pmc_ids = []
        pmids_analyzed = []
        sections_analyzed = 0
        cumulative_relevance = 0.0

    def fake_decide(**kwargs):
        seen["cumulative_relevance"] = kwargs["cumulative_relevance"]
        seen["allow"] = kwargs["allow_ortholog_fallback"]
        return aa.OrthologDecision(hit=None, skipped_reason="no_ortholog_found")

    monkeypatch.setattr(aa, "run_paper_annotation_pass", lambda *a, **k: FakePass())
    monkeypatch.setattr(aa, "_decide_ortholog_action", fake_decide)
    result = aa.get_gene_annotation(
        profile="mtb-h37rv", locus="Rv9999",
        allow_online_name_lookup=False, allow_ortholog_fallback=True,
    )
    assert seen["allow"] is True
    assert seen["cumulative_relevance"] == 0.0
    assert result["gene_annotation"] is not None
    # Must not skip as no_eligible_fields solely because target was empty
    assert result["annotation_metadata"]["ortholog_pass"]["skipped_reason"] != "no_eligible_fields"
```

If `ortholog_pass` is only on the merged annotation, assert via `result["gene_annotation"]["annotation_metadata"]["ortholog_pass"]`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_empty_annotation_json.py -v`  
Expected: FAIL

- [ ] **Step 3: Implement**

```python
# metadata.py
EMPTY_TARGET_NOTES = (
    "No papers were available for this gene; "
    "no literature-backed target annotation was produced."
)
EMPTY_ORTHOLOG_NOTES = "The ortholog pass also found no papers."


def empty_annotation_from_metadata(annotation_metadata, *, gene_id, name, profile):
    from . import field_defs
    doc = {
        "gene_id": gene_id,
        "name": name,
        "annotation_notes": EMPTY_TARGET_NOTES,
        "annotation_metadata": dict(annotation_metadata or {}),
    }
    for field_def in field_defs.resolve_effective_fields(profile):
        doc[field_def.key] = None
    doc["annotation_metadata"]["field_coverage"] = build_field_coverage(doc, profile=profile)
    return doc
```

In `get_gene_annotation`, after building `annotation_metadata` and the `if gene_distillation is not None:` block, add:

```python
if merged_annotation is None and not used:
    merged_annotation = metadata.empty_annotation_from_metadata(
        annotation_metadata,
        gene_id=gene or display_gene,
        name=name,
        profile=profile_context,
    )
```

When ortholog pass ran but `gene_distillation is None`, append `EMPTY_ORTHOLOG_NOTES` to `annotation_notes` on `merged_annotation`.

Do not change `__main__.py` early-return for `used_ids` non-empty. Zero-paper jobs now have `gene_annotation` set so the existing write path runs.

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_empty_annotation_json.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add autoannotation/metadata.py autoannotation/autoannotation.py tests/test_empty_annotation_json.py
git commit -m "feat(autoannotation): persist blank JSON and allow ortholog after no target papers"
```
