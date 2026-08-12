# Section Excerpt Chunking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Spec:** `docs/superpowers/specs/2026-08-12-section-excerpt-chunking-design.md`

**Goal:** Deterministically split oversized paper section excerpts (default 10k characters) into paragraph- then sentence-packed chunks so each chunk runs the existing 3-extractor + consensus path without LLM summarization.

**Architecture:** Add a pure `section_chunking` helper that expands `(label, text)` into capped chunks with `label#N` names; call it when building the per-paper section work list in `run_paper_annotation_pass` so progress totals and extract loops see chunks as ordinary sections. Teach `SECTION_HINTS` lookup to use the base label before `#`.

**Tech Stack:** Python 3, pytest, existing `autoannotation` extract/consensus pipeline.

## Global Constraints

- Excerpt cap default: **10_000 characters** (`len(str)`), excerpt-only (not full prompt).
- Env override: `AUTOANNOTATION_SECTION_EXCERPT_MAX_CHARS` (positive int; else default).
- Split order: paragraphs (`\n\n`) → sentences → hard-truncate single overlong sentence to cap.
- No chunk overlap in v1; no LLM summarization; no JATS re-split in v1.
- Chunk labels: base label if one piece; `{label}#1`…`#{n}` if multiple.
- TDD; no `git add .` / `git add -A` — named paths only.
- Do not change fleet context defaults in this plan.

## File map

| Path | Action | Responsibility |
|------|--------|----------------|
| `autoannotation/section_chunking.py` | Create | Cap parsing, paragraph/sentence split, pack, expand |
| `autoannotation/autoannotation.py` | Modify | Expand sections after collect; progress counts chunks |
| `autoannotation/llms.py` | Modify | `SECTION_HINTS` via base type before `#` |
| `tests/test_section_chunking.py` | Create | Unit tests for chunking helper |
| `tests/test_section_chunking_wireup.py` | Create | Expand applied to collected sections / hint base |
| `USAGE.md` or `worker/README.md` | Modify | One short note on env cap (optional, Task 4) |

---

### Task 1: Pure chunking helper + unit tests

**Files:**
- Create: `autoannotation/section_chunking.py`
- Create: `tests/test_section_chunking.py`

**Interfaces:**
- Consumes: none (stdlib only)
- Produces:
  - `DEFAULT_EXCERPT_MAX_CHARS: int = 10_000`
  - `excerpt_max_chars_from_env(environ: Mapping[str, str] | None = None) -> int`
  - `split_paragraphs(text: str) -> list[str]`
  - `split_sentences(text: str) -> list[str]`
  - `pack_units(units: list[str], *, max_chars: int, joiner: str) -> list[str]`
  - `chunk_section_text(text: str, *, max_chars: int) -> list[str]`
  - `expand_section(label: str, text: str, *, max_chars: int) -> list[tuple[str, str]]`
  - `expand_sections(sections: list[tuple[str, str]], *, max_chars: int) -> list[tuple[str, str]]`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_section_chunking.py
from autoannotation.section_chunking import (
    chunk_section_text,
    expand_section,
    expand_sections,
    excerpt_max_chars_from_env,
)


def test_under_cap_unchanged():
    text = "short paragraph"
    assert chunk_section_text(text, max_chars=100) == [text]
    assert expand_section("abstract", text, max_chars=100) == [("abstract", text)]


def test_paragraph_pack_splits_over_cap():
    p1 = "A" * 60
    p2 = "B" * 60
    text = f"{p1}\n\n{p2}"
    chunks = chunk_section_text(text, max_chars=70)
    assert chunks == [p1, p2]


def test_sentence_split_when_paragraph_too_large():
    s1 = "First sentence is long enough here."
    s2 = "Second sentence follows afterward."
    para = f"{s1} {s2}"
    assert len(para) > 40
    chunks = chunk_section_text(para, max_chars=40)
    assert all(len(c) <= 40 for c in chunks)
    assert s1 in chunks[0]


def test_expand_labels_number_when_multiple():
    p1 = "A" * 50
    p2 = "B" * 50
    out = expand_section("results", f"{p1}\n\n{p2}", max_chars=60)
    assert out == [("results#1", p1), ("results#2", p2)]


def test_excerpt_max_chars_from_env(monkeypatch):
    assert excerpt_max_chars_from_env({}) == 10_000
    assert excerpt_max_chars_from_env({"AUTOANNOTATION_SECTION_EXCERPT_MAX_CHARS": "8000"}) == 8000
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_section_chunking.py -q --tb=short`  
Expected: FAIL (module missing)

- [ ] **Step 3: Implement `autoannotation/section_chunking.py`**

Minimal behavior:

- Paragraphs: `re.split(r'\n\s*\n', text)` then strip; drop empties.
- Sentences: simple splitter on `.!?` followed by whitespace/end (good enough for v1 science prose; keep delimiter on the sentence).
- `pack_units`: greedy append while `len(current) + len(joiner) + len(unit) <= max_chars`; never break a unit inside pack — if unit alone exceeds cap, caller must pre-split (sentences) or truncate.
- `chunk_section_text`: if `len(text) <= max_chars` return `[text]`; else pack paragraphs; for any packed piece still over max (single fat paragraph), sentence-pack; for any sentence over max, `text[:max_chars]` and `logging.warning`.
- `expand_section`: map chunks to labels as specified.
- `expand_sections`: flatten `expand_section` over the list.

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_section_chunking.py -q --tb=short`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add autoannotation/section_chunking.py tests/test_section_chunking.py
git commit -m "$(cat <<'EOF'
feat(autoannotation): add deterministic section excerpt chunking helper

EOF
)"
```

(If `tests/` is gitignored, `git add -f tests/test_section_chunking.py`.)

---

### Task 2: SECTION_HINTS base-type lookup

**Files:**
- Modify: `autoannotation/llms.py` (`SECTION_HINTS` usage in `build_section_prompt`)
- Modify or extend: `tests/test_section_chunking.py` (or small `tests/test_section_hint_base.py`)

**Interfaces:**
- Consumes: chunk labels like `results#2`
- Produces: hints resolved from `results`

- [ ] **Step 1: Write failing test**

```python
from autoannotation.llms import build_section_prompt, SECTION_HINTS

def test_build_section_prompt_uses_base_type_for_chunk_labels():
    prompt = build_section_prompt(
        "Rv0001", "dnaA", "excerpt text", section_type="results#2",
    )
    assert SECTION_HINTS["results"] in prompt
    assert "Section type: results#2" in prompt
```

- [ ] **Step 2: Run test — expect FAIL** (hint missing)

- [ ] **Step 3: Implement**

In `build_section_prompt`, when looking up hints:

```python
base_type = section_type.split("#", 1)[0]
hint = SECTION_HINTS.get(base_type, "")
```

Keep displaying the full `section_type` in the prompt (`Section type: results#2`).

- [ ] **Step 4: Run test — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add autoannotation/llms.py tests/test_section_chunking.py
git commit -m "$(cat <<'EOF'
fix(autoannotation): resolve SECTION_HINTS from chunk base type

EOF
)"
```

---

### Task 3: Wire expand into annotation pass + progress totals

**Files:**
- Modify: `autoannotation/autoannotation.py` (`run_paper_annotation_pass` section pre-scan / loop)
- Create: `tests/test_section_chunking_wireup.py`

**Interfaces:**
- Consumes: `expand_sections`, `excerpt_max_chars_from_env`
- Produces: extract loop iterates capped chunks; `sections_total` counts chunks

- [ ] **Step 1: Write failing wireup test**

Prefer testing a small helper if you extract one, e.g. `_sections_for_extraction(paper_manager, pmc_id, max_chars=...)`, to avoid full LLM/network:

```python
def test_sections_for_extraction_expands_oversize(monkeypatch):
    # stub collect_paper_sections to return one fat results blob
    ...
    sections = _sections_for_extraction(fake_pm, "1", max_chars=100)
    assert all(len(text) <= 100 for _, text in sections)
    assert len(sections) >= 2
```

Or monkeypatch `collect_paper_sections` inside `autoannotation.autoannotation` and call the helper used by the pass.

- [ ] **Step 2: Run test — expect FAIL**

- [ ] **Step 3: Wire into `run_paper_annotation_pass`**

Around the existing pre-scan:

```python
from autoannotation.section_chunking import (
    expand_sections,
    excerpt_max_chars_from_env,
)

max_chars = excerpt_max_chars_from_env()
papers_sections = [
    (pmc_id, expand_sections(collect_paper_sections(paper_manager, pmc_id), max_chars=max_chars))
    for pmc_id in papers_to_analyze
]
sections_total = sum(len(sections) for _, sections in papers_sections)
```

No other loop changes required: `for label, section in sections` already drives extractors + consensus + progress.

Optional: `log.info` when expansion increases count for a paper.

- [ ] **Step 4: Run wireup + chunking tests — expect PASS**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_section_chunking.py tests/test_section_chunking_wireup.py -q --tb=short`

- [ ] **Step 5: Commit**

```bash
git add autoannotation/autoannotation.py tests/test_section_chunking_wireup.py
git commit -m "$(cat <<'EOF'
feat(autoannotation): expand oversized sections before extraction

EOF
)"
```

---

### Task 4: Docs + regression gate

**Files:**
- Modify: `USAGE.md` (short env note near autoannotation/model settings) **or** `worker/README.md` if that is where operator knobs live — prefer wherever `AUTOANNOTATION_*` knobs are already documented.

- [ ] **Step 1: Document**

Add something like:

```markdown
`AUTOANNOTATION_SECTION_EXCERPT_MAX_CHARS` — max characters of paper excerpt
per extractor call (default 10000). Oversized abstract/results/discussion
text is split on paragraphs, then sentences; each chunk gets its own
extractors + consensus.
```

- [ ] **Step 2: Run focused suite**

```bash
PYTHONPATH=. .venv/bin/python -m pytest \
  tests/test_section_chunking.py \
  tests/test_section_chunking_wireup.py \
  -q --tb=short
```

Expected: all PASS

- [ ] **Step 3: Commit**

```bash
git add USAGE.md   # or the doc file you edited
git commit -m "$(cat <<'EOF'
docs: document section excerpt chunk size env knob

EOF
)"
```

---

## Done when

- Oversized sections never enter extractors above the char cap (except truncated single-sentence safety case already at cap).
- Short sections unchanged (same labels, one unit).
- Chunk labels get correct `SECTION_HINTS`.
- Dashboard progress totals count chunks.
- Focused pytest suite green.
