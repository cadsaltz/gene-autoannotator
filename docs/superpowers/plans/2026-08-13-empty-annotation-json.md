# Empty Annotation JSON Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Spec:** `docs/superpowers/specs/2026-08-13-empty-annotation-json-design.md`

**Goal:** Write a blank schema-shaped annotation JSON when a job analyzes zero papers, with no LLM calls and no change to jobs that have papers.

**Architecture:** After `get_gene_annotation`, if there is no distillation and `used_ids` is empty, build a null-field annotation from existing metadata and write it with the current output-path logic.

**Tech Stack:** Python 3, pytest, `autoannotation/__main__.py`, `autoannotation/metadata.py` or `field_defs.py`.

## Global Constraints

- Trigger only when `gene_annotation is None` and `gene_distillation is None` and `used_ids` is empty.
- Do not call Ollama. Do not change `get_gene_annotation` ortholog gating.
- Jobs with any analyzed paper: unchanged.
- `annotation_notes` states that no papers were available.
- Same `gen_<id>.json` path rules as today.
- TDD; named git paths only.

## File map

| Path | Action | Responsibility |
|------|--------|----------------|
| `autoannotation/metadata.py` | Modify | `empty_annotation_from_metadata(...)` helper |
| `autoannotation/__main__.py` | Modify | Use helper instead of early return |
| `tests/test_empty_annotation_json.py` | Create | Helper + persist trigger |

---

### Task 1: Blank annotation helper + persist when no papers analyzed

**Files:**
- Modify: `autoannotation/metadata.py`
- Modify: `autoannotation/__main__.py`
- Create: `tests/test_empty_annotation_json.py`

**Interfaces:**
- Produces: `empty_annotation_from_metadata(annotation_metadata, *, gene_id, name, profile) -> dict`
- Notes constant: `'No papers were available for this gene; no literature-backed annotation was produced.'`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_empty_annotation_json.py
from autoannotation import metadata
from autoannotation.organisms import resolve_profile


def test_empty_annotation_null_fields_and_notes():
    profile = resolve_profile("mtb-h37rv")
    meta = {
        "profile_id": "mtb-h37rv",
        "literature": {"papers_analyzed": 0},
        "quality_flags": ["no_papers_retrieved", "no_papers_analyzed"],
    }
    doc = metadata.empty_annotation_from_metadata(
        meta, gene_id="Rv9999", name="fake", profile=profile,
    )
    assert doc["gene_id"] == "Rv9999"
    assert doc["name"] == "fake"
    assert doc["function"] is None
    assert doc["functional_category"] is None
    assert doc["annotation_notes"] == (
        "No papers were available for this gene; "
        "no literature-backed annotation was produced."
    )
    assert doc["annotation_metadata"]["field_coverage"]["function"] == "insufficient_evidence"
    assert "go_terms" not in doc


def test_main_writes_json_when_no_papers(tmp_path, monkeypatch):
    from autoannotation import __main__ as cli

    fake = {
        "gene_distillation": None,
        "gene_annotation": None,
        "pmc_ids": [],
        "used_ids": [],
        "cumulative_relevance": 0.0,
        "selection_mode": "all_eligible_limited_literature",
        "annotation_metadata": {
            "profile_id": "mtb-h37rv",
            "resolved_locus": "Rv9999",
            "resolved_name": None,
        },
    }
    monkeypatch.setattr(cli, "get_gene_annotation", lambda **kwargs: fake)
    result = cli.main(profile="mtb-h37rv", locus="Rv9999", output_dir=str(tmp_path), quiet=True)
    path = tmp_path / "gen_Rv9999.json"
    assert path.is_file()
    assert result["output_path"] == str(path)


def test_main_still_skips_write_when_papers_used_but_no_distillation(tmp_path, monkeypatch):
    from autoannotation import __main__ as cli

    fake = {
        "gene_distillation": None,
        "gene_annotation": None,
        "pmc_ids": ["1"],
        "used_ids": ["1"],
        "cumulative_relevance": 1.0,
        "selection_mode": "cumulative_relevance_budget",
        "annotation_metadata": {"profile_id": "mtb-h37rv"},
    }
    monkeypatch.setattr(cli, "get_gene_annotation", lambda **kwargs: fake)
    result = cli.main(profile="mtb-h37rv", locus="Rv0001", output_dir=str(tmp_path), quiet=True)
    assert result is None
    assert not (tmp_path / "gen_Rv0001.json").exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_empty_annotation_json.py -v`  
Expected: FAIL (`empty_annotation_from_metadata` missing; main still returns without write)

- [ ] **Step 3: Implement helper + `__main__` branch**

```python
# autoannotation/metadata.py
EMPTY_ANNOTATION_NOTES = (
    "No papers were available for this gene; "
    "no literature-backed annotation was produced."
)


def empty_annotation_from_metadata(annotation_metadata, *, gene_id, name, profile):
    from . import field_defs

    doc = {
        "gene_id": gene_id,
        "name": name,
        "annotation_notes": EMPTY_ANNOTATION_NOTES,
        "annotation_metadata": dict(annotation_metadata or {}),
    }
    for field_def in field_defs.resolve_effective_fields(profile):
        doc[field_def.key] = None
    doc["annotation_metadata"]["field_coverage"] = build_field_coverage(doc, profile=profile)
    return doc
```

In `__main__.py`, replace the early return:

```python
if parsed is None:
    if result.get("gene_distillation") is None:
        used = result.get("used_ids") or []
        if used:
            if not quiet:
                print(f"No annotation produced for {output_gene}")
            return
        from autoannotation import metadata as metadata_mod
        from autoannotation import organisms
        meta = result.get("annotation_metadata") or {}
        profile_id = meta.get("profile_id") or profile or "mtb-h37rv"
        profile_obj = organisms.profile_from_mapping(profile_config) if profile_config else organisms.resolve_profile(profile_id)
        parsed = metadata_mod.empty_annotation_from_metadata(
            meta,
            gene_id=meta.get("resolved_locus") or output_gene,
            name=meta.get("resolved_name") or name,
            profile=profile_obj,
        )
```

Then fall through to the existing `os.makedirs` / `json.dump` path.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_empty_annotation_json.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add autoannotation/metadata.py autoannotation/__main__.py tests/test_empty_annotation_json.py
git commit -m "feat(autoannotation): write blank JSON when no papers analyzed"
```
