# Section Excerpt Chunking Design

**Date:** 2026-08-12  
**Status:** Approved for implementation planning  
**Scope:** Deterministic splitting of oversized paper section excerpts before extractor / consensus LLM calls. No LLM summarization.

## Problem

Paper sections fed to extractors range roughly from ~1k to ~100k characters. There is no application-level size limit today (`collect_paper_sections` → full text → `build_section_prompt`). Oversized excerpts caused truncation under smaller Ollama contexts; raising fleet `OLLAMA_CONTEXT_LENGTH` reduced truncation but increased memory pressure and weakened extraction quality. Factual accuracy favors smaller, clearer excerpts.

## Goals

- Cap each extractor **excerpt** at a fixed character budget (default **10_000**).
- Split only when over budget: **paragraphs first**, then **sentences**.
- Treat each chunk as its own section unit: **3 extractors + consensus** per chunk (existing path).
- Remain fully deterministic (no model summarization).
- Preserve `SECTION_HINTS` behavior for abstract / results / discussion.
- Make progress totals (`sections_total`) reflect post-split work items.

## Non-goals (v1)

- JATS subsection restoration as first-class units (future enhancement).
- Gene-mention window filtering.
- Chunk overlap.
- Changing aggregation, GO resolve, or fleet context defaults in this change (fleet may be tuned separately once excerpts are bounded).
- Token-exact budgeting (chars are the v1 proxy).

## Design

### Placement

Add a pure helper that expands `(label, text)` lists **after** `collect_paper_sections` and **before** the extract loop / progress pre-scan count.

Recommended module: `autoannotation/section_chunking.py`  
Wire-in: `autoannotation/autoannotation.py` inside `run_paper_annotation_pass` when building `papers_sections` (or immediately after `collect_paper_sections` per paper).

### Algorithm

```
expand_section(label, text, max_chars) -> list[(chunk_label, chunk_text)]

if len(text) <= max_chars:
    return [(label, text)]

paragraphs = split on blank lines (keep non-empty)
chunks = pack paragraphs greedily into groups with len <= max_chars
  (join with "\n\n")
for any paragraph still > max_chars:
    replace with sentence-packed pieces (join with " ")
if a single sentence still > max_chars:
    hard-truncate to max_chars (last-resort safety; log warning)
assign chunk labels: "{label}" for one chunk; "{label}#1", "{label}#2", ... when multiple
```

- Measure size with **Python `len(str)` characters**, not bytes.
- Cap applies to **excerpt text only**, not the fixed prompt template / field list.
- Default `max_chars = 10_000`.
- Override via env: `AUTOANNOTATION_SECTION_EXCERPT_MAX_CHARS` (positive int; invalid/empty → default).

### Prompt / hints

`SECTION_HINTS` keys are `abstract` | `results` | `discussion`. Chunk labels like `results#2` must resolve hints via **base type** (`section_type.split('#', 1)[0]`).

### Downstream

- Extract + consensus loops unchanged aside from iterating expanded sections.
- Aggregation already merges many per-PMID section JSON objects; multiple `results#N` rows are fine.
- Cached LLM responses key on full prompt text → chunks naturally get distinct cache entries.

### Progress

`sections_total` / `sections_done` count **expanded** chunks so the dashboard reflects real extractor units.

### Ops / expected cost

- Sections under the cap: **0** extra calls.
- A 20k-char section → ~2 chunks → ~2× extractor+consensus calls for that section; decode work ~2×; prefill on body text roughly similar order plus duplicated template overhead.
- Pathological 100k sections pay for many chunks; that is intentional vs one unbounded prompt.

## Testing

- Unit tests for pack/split edge cases (under cap, exact cap, paragraph split, sentence split, oversized sentence truncate, label numbering).
- Integration-style test that `run_paper_annotation_pass` (or a thin wrapper) expands before counting sections — mock LLM if needed, or test only the expand call site helper.

## Success criteria

- No excerpt longer than the configured cap enters `build_section_prompt` / extractors (except documented hard-truncate of a single overlong sentence already cut to cap).
- Abstracts and short sections behaviorally unchanged.
- Existing consensus + aggregation still produce gene-level JSON without schema changes.
