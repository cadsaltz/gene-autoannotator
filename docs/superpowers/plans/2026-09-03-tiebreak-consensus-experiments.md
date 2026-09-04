# Tie-break Consensus Experiments Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the approved tie-break suite: expand constructed fixtures via subagents (dummy extractor responses from expected + majority/minority briefs), add a general consensus prompt helper, and ship one thin runner that writes the paper artifact contract for `tiebreak-nonsense` and `tiebreak-non-nonsense`.

**Architecture:** Author a locked **brief catalog** (expected answer + agreement pattern per case). Dispatch subagents to fill `candidates[]` only. Validate and merge into `tiebreak_consensus_v1.json`. Runner calls existing `hybrid_section_consensus(..., excerpt=None)` with biology or general `batch_merger`, scores vs labeled `expected`, and emits manifest / records / aggregate. Two YAML configs filter the same fixture by `experiment_tags`.

**Tech Stack:** Python 3.11+, existing `autoannotation.consensus` / `autoannotation.llms`, PyYAML, pytest, Ollama (live consensus model for non-dry runs).

**Design spec:** `docs/superpowers/specs/2026-09-03-tiebreak-consensus-experiments-design.md`

## Global Constraints

- `excerpt=None` on every hybrid call (no excerpt gate).
- Every case has one clear `expected` majority/reconciled label.
- Majority nonsense **must be adopted** when that is the majority (trust extractors).
- ~25% `expect_llm=false` / ~75% `expect_llm=true` across the full suite.
- Thin runner only — do not fork a second annotation pipeline.
- Reuse `experiments/paper/runners/common.py` artifact helpers where possible.
- Subagents **generate candidates from briefs**; they do not invent new expected answers unless the brief leaves `expected` blank (briefs should usually provide `expected`).
- Pin exact consensus model tag in YAML before runnable status.
- Artifact contract: `results/<experiment_id>/<run_id>/{manifest.json,records.jsonl,aggregate.csv}`.
- Out of scope: bias/split/cost, Gemini, GO, ortholog, false-cognates, relevance.

---

## File map (target)

| Path | Role |
|------|------|
| `experiments/paper/fixtures/constructed/tiebreak_briefs_v1.json` | Locked briefs: expected + majority/minority distribution (no candidates yet, or stubs) |
| `experiments/paper/fixtures/constructed/tiebreak_consensus_v1.json` | Full cases after subagent fill (source of truth for runs) |
| `experiments/paper/fixtures/constructed/SUBAGENT_CASE_PROMPT.md` | Copy-paste prompt template for case-generation subagents |
| `experiments/paper/runners/tiebreak_matching.py` | `match_exact` / `match_soft` / invention helpers |
| `experiments/paper/runners/tiebreak_fixture.py` | Load/filter/validate fixture + briefs |
| `experiments/paper/runners/general_consensus.py` | General merge prompt + Ollama batch merger for `domain=general` |
| `experiments/paper/runners/run_tiebreak_consensus.py` | CLI runner |
| `experiments/paper/configs/tiebreak-nonsense.yaml` | Filter + pinned model |
| `experiments/paper/configs/tiebreak-non-nonsense.yaml` | Filter + pinned model |
| `experiments/paper/analysis/tiebreak_consensus.md` | Operator commands + how to read aggregates |
| `experiments/paper/tests/test_tiebreak_matching.py` | Unit tests for matching |
| `experiments/paper/tests/test_tiebreak_fixture.py` | Fixture validation tests |
| `experiments/paper/tests/test_tiebreak_runner_dry.py` | Dry-run with mock merger |
| `experiments/paper/PROTOCOL.md` | Registry status updates |

---

### Task 1: Matching helpers (TDD)

**Files:**
- Create: `experiments/paper/runners/tiebreak_matching.py`
- Create: `experiments/paper/tests/test_tiebreak_matching.py`

**Interfaces:**
- Consumes: `autoannotation.consensus.token_jaccard`, `autoannotation.consensus._string_traceable_to_candidates` (or re-export via thin wrappers)
- Produces:
  - `match_exact(observed, expected) -> bool`
  - `match_soft(observed, expected, *, kind: str = "string") -> bool` — string: token Jaccard ≥ 0.50; boolean/array: exact-after-normalize; both-null → True
  - `is_invention(observed, candidate_values: list[str]) -> bool` — False if null; else not traceable to candidates

- [ ] **Step 1: Write the failing tests**

```python
# experiments/paper/tests/test_tiebreak_matching.py
from experiments.paper.runners.tiebreak_matching import (
    is_invention,
    match_exact,
    match_soft,
)

def test_match_exact_normalizes_whitespace_case():
    assert match_exact("Apples Are Red", "apples are red")
    assert not match_exact("apples are green", "apples are red")

def test_match_soft_jaccard_threshold():
    assert match_soft(
        "apples are red and delicious",
        "apples are red and delicious",
    )
    assert match_soft(
        "red delicious apples",
        "apples are red and delicious",
    )
    assert not match_soft("completely unrelated text here", "apples are red and delicious")

def test_match_both_null():
    assert match_exact(None, None)
    assert match_soft(None, None)

def test_invention_detects_novel_string():
    cands = ["zorblin is quantex-bright", "the zorblin is quantex bright"]
    assert is_invention("photosynthesis in chloroplasts", cands)
    assert not is_invention("zorblin is quantex-bright", cands)
    assert not is_invention(None, cands)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest experiments/paper/tests/test_tiebreak_matching.py -v`  
Expected: FAIL (import / missing module)

- [ ] **Step 3: Implement `tiebreak_matching.py`**

```python
# experiments/paper/runners/tiebreak_matching.py
from __future__ import annotations
from typing import Any
from autoannotation.consensus import token_jaccard, _string_traceable_to_candidates
from experiments.paper.runners.common import is_nullish, field_values_equal

SOFT_JACCARD = 0.50

def match_exact(observed: Any, expected: Any) -> bool:
    if is_nullish(observed) and is_nullish(expected):
        return True
    if is_nullish(observed) or is_nullish(expected):
        return False
    return " ".join(str(observed).lower().split()) == " ".join(str(expected).lower().split())

def match_soft(observed: Any, expected: Any, *, kind: str = "string") -> bool:
    if kind in {"boolean", "array"}:
        return field_values_equal(observed, expected, kind=kind)
    if is_nullish(observed) and is_nullish(expected):
        return True
    if is_nullish(observed) or is_nullish(expected):
        return False
    return token_jaccard(str(observed), str(expected)) >= SOFT_JACCARD

def is_invention(observed: Any, candidate_values: list[str]) -> bool:
    if is_nullish(observed):
        return False
    return not _string_traceable_to_candidates(str(observed), [str(v) for v in candidate_values])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest experiments/paper/tests/test_tiebreak_matching.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add experiments/paper/runners/tiebreak_matching.py experiments/paper/tests/test_tiebreak_matching.py
git commit -m "feat(paper): add tie-break expected-match helpers"
```

---

### Task 2: Brief catalog + subagent prompt template

**Files:**
- Create: `experiments/paper/fixtures/constructed/tiebreak_briefs_v1.json`
- Create: `experiments/paper/fixtures/constructed/SUBAGENT_CASE_PROMPT.md`
- Modify: keep starter rows in `tiebreak_consensus_v1.json` until Task 3 merges

**Interfaces:**
- Produces: brief objects with locked `expected` + `agreement` block (no `candidates` yet)
- Target suite size: **32 briefs** → ~8 `expect_llm=false` (25%), ~24 `expect_llm=true` (75%)
- Domains: ≥10 `general`, ≥10 `biology`
- Tags: ≥12 `tiebreak-nonsense`, ≥16 `tiebreak-non-nonsense` (some cases may only have one tag)

**Brief schema (required keys):**

```json
{
  "brief_id": "general-apples-paraphrase-001",
  "domain": "general",
  "case_family": "paraphrase_majority",
  "experiment_tags": ["tiebreak-non-nonsense"],
  "field_key": "answer",
  "expect_llm": true,
  "expected": "apples are red and delicious",
  "agreement": {
    "majority_count": 2,
    "minority_count": 1,
    "majority_mode": "paraphrase",
    "minority_role": "conflict",
    "extractor_0_is_minority": true
  },
  "identity": null,
  "notes": "Paper walkthrough example."
}
```

For biology: `"field_key": "function"`, `"identity": {"gene_id": "Rv0001", "name": "dnaA"}`, and `expected` is the majority function string (or null for hard splits).

**Agreement rules for authors of briefs:**

| `majority_mode` | Meaning for subagents |
|-----------------|----------------------|
| `exact` | Exactly `majority_count` candidates use the **same string** as `expected` (character-identical after trim). Minority differs. `expect_llm` must be false. |
| `paraphrase` | `majority_count` candidates paraphrase `expected` with **different wording** (not identical to each other or to `expected` byte-for-byte). Share enough content tokens that pairwise Jaccard among majority ≥ ~0.35. Minority conflicts. `expect_llm` must be true. |
| `none` | Three mutually incompatible values; `expected` is `null`. |

Always use 3 candidates total: `majority_count + minority_count == 3` (typically 2+1). For `hard_split_null`, set `majority_count=0`, `minority_count=3`, `majority_mode=none`.

- [ ] **Step 1: Write `SUBAGENT_CASE_PROMPT.md`** with this exact template body (implementer pastes brief JSON into `{BRIEF_JSON}`):

```markdown
# Tie-break case generation

You generate **three dummy extractor JSON objects** for one consensus trial.
Do **not** change `expected`, `expect_llm`, `case_family`, or `agreement`.

## Brief (authoritative)

```json
{BRIEF_JSON}
```

## Rules

1. Output a single JSON object with keys:
   - all brief fields unchanged (`brief_id` becomes `case_id`)
   - `candidates`: array of exactly 3 objects
2. Each candidate must contain at least `field_key` from the brief.
   - `domain=general`: `{"answer": "..."}` (optional extra keys ok but unused)
   - `domain=biology`: include `gene_id`, `name` from `identity`, plus `function` (and nulls for other biology fields if convenient)
3. Honor `agreement`:
   - `majority_mode=exact`: `majority_count` candidates use the **exact** `expected` string; minority conflicts.
   - `majority_mode=paraphrase`: `majority_count` candidates are **non-identical paraphrases** of `expected` (vary wording/order; keep shared content words); minority conflicts with different meaning.
   - `majority_mode=none`: three incompatible values; no majority; field value can be anything mutually conflicting; expected remains null.
4. If `extractor_0_is_minority` is true, `candidates[0]` must be the conflicting/wrong value.
5. For nonsense families, majority strings are made-up words/phrases (e.g. zorblin, quantex); still follow exact vs paraphrase mode.
6. Do not include source excerpts. Do not call tools. Do not explain — return JSON only.

## Output shape

```json
{
  "case_id": "<brief_id>",
  "domain": "...",
  "case_family": "...",
  "experiment_tags": [],
  "field_key": "...",
  "expect_llm": true,
  "expected": "...",
  "candidates": [{}, {}, {}],
  "notes": "..."
}
```
```

- [ ] **Step 2: Author all 32 briefs in `tiebreak_briefs_v1.json`**

Include at minimum:
- `general-apples-paraphrase-001` (expected: `apples are red and delicious`, 2 paraphrase majority, extractor_0 minority)
- ≥4 `exact_majority` / `exact_majority_nonsense` (`expect_llm=false`)
- ≥4 `paraphrase_majority` / `paraphrase_majority_nonsense` (`expect_llm=true`)
- ≥4 biology `function` cases (mix exact + paraphrase)
- ≥2 `hard_split_null`
- ≥6 necessity-friendly cases with `extractor_0_is_minority: true`

Suggested family counts (adjust slightly if needed to hit 25/75):

| Family | Count | expect_llm |
|--------|------:|------------|
| exact_majority | 4 | false |
| exact_majority_nonsense | 4 | false |
| paraphrase_majority | 10 | true |
| paraphrase_majority_nonsense | 8 | true |
| hard_split_null | 2 | true |
| minority_error (exact or paraphrase tagged) | 4 | mix — can overlap families via notes; or fold into above with extractor_0 minority |

Prefer folding necessity into the rows above via `extractor_0_is_minority` rather than a separate family count explosion. Final file must have **exactly 32** briefs and **exactly 8** with `expect_llm=false`.

- [ ] **Step 3: Sanity-check brief file with a one-off Python snippet**

```bash
python - <<'PY'
import json
from pathlib import Path
p = Path("experiments/paper/fixtures/constructed/tiebreak_briefs_v1.json")
data = json.loads(p.read_text())
items = data["items"]
assert len(items) == 32, len(items)
n_det = sum(1 for i in items if not i["expect_llm"])
assert n_det == 8, n_det
assert all("expected" in i and "agreement" in i for i in items)
print("briefs ok", n_det, "deterministic", 32-n_det, "llm")
PY
```

Expected: `briefs ok 8 deterministic 24 llm`

- [ ] **Step 4: Commit**

```bash
git add experiments/paper/fixtures/constructed/tiebreak_briefs_v1.json \
  experiments/paper/fixtures/constructed/SUBAGENT_CASE_PROMPT.md
git commit -m "docs(paper): lock tie-break case briefs and subagent prompt"
```

---

### Task 3: Subagent-generated candidates → merge fixture

**Files:**
- Modify: `experiments/paper/fixtures/constructed/tiebreak_consensus_v1.json`
- Create: `experiments/paper/runners/tiebreak_fixture.py`
- Create: `experiments/paper/tests/test_tiebreak_fixture.py`

**Interfaces:**
- Consumes: briefs + subagent case JSON
- Produces: `load_tiebreak_fixture(path) -> list[dict]`, `filter_cases(items, experiment_tags)`, `validate_case(case) -> list[str]` (error messages)

**Subagent execution (required for this task):**

- [ ] **Step 1: Dispatch case-generation subagents in parallel batches**

Use `Task` / generalPurpose subagents (or equivalent). For each brief in `tiebreak_briefs_v1.json`:

1. Read `SUBAGENT_CASE_PROMPT.md`, substitute `{BRIEF_JSON}` with that brief.
2. Ask the subagent to return **JSON only** for one case.
3. Save raw outputs under `experiments/paper/fixtures/constructed/generated_raw/<brief_id>.json` (gitignored if bulky; or commit if small).

Recommended batching: 4–8 briefs per subagent wave to avoid context overload; do not ask one subagent to invent all 32 from scratch without briefs.

Parent agent must **not** rewrite `expected` or `agreement` when merging.

- [ ] **Step 2: Write fixture validation tests (fail first)**

```python
# experiments/paper/tests/test_tiebreak_fixture.py
import json
from pathlib import Path
from experiments.paper.runners.tiebreak_fixture import validate_case, filter_cases, load_tiebreak_fixture

FIXTURE = Path("experiments/paper/fixtures/constructed/tiebreak_consensus_v1.json")

def test_suite_mix_and_size():
    items = load_tiebreak_fixture(FIXTURE)
    assert len(items) == 32
    assert sum(1 for i in items if not i["expect_llm"]) == 8

def test_apples_case_present():
    items = load_tiebreak_fixture(FIXTURE)
    apples = next(i for i in items if i["case_id"] == "general-apples-paraphrase-001")
    assert apples["expected"] == "apples are red and delicious"
    assert len(apples["candidates"]) == 3

def test_validate_exact_majority_has_two_identical():
    case = {
        "case_id": "x",
        "domain": "general",
        "case_family": "exact_majority",
        "experiment_tags": ["tiebreak-non-nonsense"],
        "field_key": "answer",
        "expect_llm": False,
        "expected": "the sky is blue",
        "candidates": [
            {"answer": "the sky is blue"},
            {"answer": "nope"},
            {"answer": "the sky is blue"},
        ],
    }
    assert validate_case(case) == []

def test_filter_by_experiment_tag():
    items = load_tiebreak_fixture(FIXTURE)
    nonsense = filter_cases(items, ["tiebreak-nonsense"])
    assert nonsense and all("tiebreak-nonsense" in i["experiment_tags"] for i in nonsense)
```

- [ ] **Step 3: Implement `tiebreak_fixture.py` validators**

Validation rules:
- exactly 3 candidates
- `field_key` present on each candidate
- if `expect_llm` is false and family starts with `exact_`: ≥2 candidates equal normalized `expected`
- if `expect_llm` is true and family starts with `paraphrase_`: fewer than 2 candidates equal normalized `expected` (so deterministic majority does not short-circuit), and at least one pair among non-minority candidates has `token_jaccard >= 0.35`
- if `expected` is null: all three candidate field values mutually non-matching under `match_exact`
- if brief/notes require extractor_0 minority: `match_soft(candidates[0][field], expected)` is False when expected is non-null

- [ ] **Step 4: Merge subagent outputs into `tiebreak_consensus_v1.json`**

```json
{
  "fixture_id": "tiebreak_consensus_v1",
  "selection_criteria": "...",
  "schema_version": 1,
  "items": [ /* 32 cases */ ]
}
```

Re-run validation until `validate_case` is empty for every item. Manually fix any subagent failures (wrong majority count, identical paraphrases, etc.) — do not silently change `expected`.

- [ ] **Step 5: Run tests**

Run: `pytest experiments/paper/tests/test_tiebreak_fixture.py -v`  
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add experiments/paper/fixtures/constructed/tiebreak_consensus_v1.json \
  experiments/paper/runners/tiebreak_fixture.py \
  experiments/paper/tests/test_tiebreak_fixture.py
git commit -m "feat(paper): fill tie-break fixture from subagent-generated candidates"
```

Update `PROTOCOL.md`: both tie-break experiments → `fixtures-ready`.

---

### Task 4: General consensus prompt + batch merger

**Files:**
- Create: `experiments/paper/runners/general_consensus.py`
- Create: `experiments/paper/tests/test_general_consensus_prompt.py`
- Modify: none of production `autoannotation/llms.py` unless you choose to export a shared constant — prefer experiment-local prompt to avoid pipeline risk

**Interfaces:**
- Produces:
  - `GENERAL_FIELD_SPECS` = `(FieldSpec("answer", "string"),)` (extend later if needed)
  - `GENERAL_BATCH_CONSENSUS_PROMPT` template with `{candidates_json}` and `{field_list}`
  - `make_general_batch_merger(model: str) -> BatchMerger`
  - `make_biology_batch_merger(llm_handler) -> BatchMerger` wrapping existing `LLMHandler._ollama_batch_consensus_merge` / public consensus entry

Prompt rules (must match biology spirit): candidates only; majority/paraphrase; no invention; null on irreconcilable conflict; no source text.

- [ ] **Step 1: Failing test — prompt mentions candidates-only and majority**

```python
from experiments.paper.runners.general_consensus import GENERAL_BATCH_CONSENSUS_PROMPT

def test_general_prompt_is_candidate_only():
    assert "do not have access to the source text" in GENERAL_BATCH_CONSENSUS_PROMPT.lower() \
        or "candidates only" in GENERAL_BATCH_CONSENSUS_PROMPT.lower() \
        or "only from the candidate" in GENERAL_BATCH_CONSENSUS_PROMPT.lower()
    assert "majority" in GENERAL_BATCH_CONSENSUS_PROMPT.lower()
```

- [ ] **Step 2: Implement prompt + merger**

`make_general_batch_merger` should call Ollama chat with JSON schema for the requested fields (mirror `_ollama_batch_consensus_merge` pattern: format prompt, parse JSON object, return dict).

For biology, construct merger that calls existing handler method with `excerpt` unused / not passed into validation path when runner sets `excerpt=None` on hybrid.

- [ ] **Step 3: Run unit test (no live Ollama required for prompt test)**

Run: `pytest experiments/paper/tests/test_general_consensus_prompt.py -v`  
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add experiments/paper/runners/general_consensus.py \
  experiments/paper/tests/test_general_consensus_prompt.py
git commit -m "feat(paper): add general consensus prompt for tie-break trials"
```

---

### Task 5: Runner + dry-run tests

**Files:**
- Create: `experiments/paper/runners/run_tiebreak_consensus.py`
- Create: `experiments/paper/tests/test_tiebreak_runner_dry.py`
- Modify: `experiments/paper/configs/tiebreak-nonsense.yaml` (pin model)
- Modify: `experiments/paper/configs/tiebreak-non-nonsense.yaml` (pin model)
- Modify: `experiments/paper/PROTOCOL.md`
- Create: `experiments/paper/analysis/tiebreak_consensus.md`

**Interfaces:**
- CLI: `python -m experiments.paper.runners.run_tiebreak_consensus --config experiments/paper/configs/tiebreak-non-nonsense.yaml [--dry-run] [--run-id ID] [--limit N]`
- `--dry-run`: use a mock `batch_merger` that returns majority paraphrase heuristically (or first non-null majority by soft match) **without** calling Ollama — still exercises deterministic path and artifact writes
- Live mode: real Ollama consensus model from config `models.consensus`

**Runner loop:**

1. Load config + fixture; `filter_cases` by `config_filter.experiment_tags`
2. For each case:
   - baseline: `observed = candidates[0][field_key]`, `llm_invoked=False`, `provenance=extractor_0`
   - hybrid: `merged, provenance, llm_calls = hybrid_section_consensus(candidates, excerpt=None, expected_gene_id=..., expected_name=..., fields=..., batch_merger=...)`
   - `observed = merged[field_key]`; `llm_invoked = llm_calls > 0` or provenance value `llm_batch_merge`
3. Score match_exact/soft/invention; write JSONL rows for both conditions
4. Write aggregate rates from spec

Pin consensus model to the repo lite consensus default unless lead specifies otherwise, e.g. `qwen3:0.6b` or current `MODEL_CONSENSUS` from lite mode — **read `autoannotation/models.py` at implement time and pin the exact tag string in both YAMLs**.

- [ ] **Step 1: Write dry-run test with mock merger**

```python
# experiments/paper/tests/test_tiebreak_runner_dry.py
from pathlib import Path
from experiments.paper.runners.run_tiebreak_consensus import run_experiment

def test_dry_run_writes_artifacts(tmp_path, monkeypatch):
    # point results dir to tmp_path via arg or env
    out = run_experiment(
        config_path=Path("experiments/paper/configs/tiebreak-non-nonsense.yaml"),
        run_id="drytest",
        dry_run=True,
        limit=2,
        results_root=tmp_path,
    )
    run_dir = Path(out)
    assert (run_dir / "manifest.json").is_file()
    assert (run_dir / "records.jsonl").is_file()
    assert (run_dir / "aggregate.csv").is_file()
    lines = (run_dir / "records.jsonl").read_text().strip().splitlines()
    assert len(lines) >= 2  # at least baseline+hybrid for one case, or 4 for two cases
    rec = __import__("json").loads(lines[0])
    assert "llm_invoked" in rec
    assert "expected" in rec and "observed" in rec
```

- [ ] **Step 2: Implement runner**

Reuse `load_yaml_config`, `write_json`, `append_jsonl`, `write_aggregate_csv`, `new_run_id`, `stable_json_hash` from `common.py`.

Biology identity: from case `identity` or defaults `gene_id="GENE1"`, `name="gene"`.

- [ ] **Step 3: Run dry-run test**

Run: `pytest experiments/paper/tests/test_tiebreak_runner_dry.py -v`  
Expected: PASS

- [ ] **Step 4: Manual dry-run both configs**

```bash
python -m experiments.paper.runners.run_tiebreak_consensus \
  --config experiments/paper/configs/tiebreak-non-nonsense.yaml --dry-run --limit 3
python -m experiments.paper.runners.run_tiebreak_consensus \
  --config experiments/paper/configs/tiebreak-nonsense.yaml --dry-run --limit 3
```

Expected: artifact dirs created; records include `llm_invoked` true/false.

- [ ] **Step 5: Write `analysis/tiebreak_consensus.md`** with operator commands for live runs and which aggregate columns feed the paper table.

- [ ] **Step 6: Update PROTOCOL registry** → `runnable` for both tie-break ids; revision log entry.

- [ ] **Step 7: Commit**

```bash
git add experiments/paper/runners/run_tiebreak_consensus.py \
  experiments/paper/tests/test_tiebreak_runner_dry.py \
  experiments/paper/configs/tiebreak-nonsense.yaml \
  experiments/paper/configs/tiebreak-non-nonsense.yaml \
  experiments/paper/analysis/tiebreak_consensus.md \
  experiments/paper/PROTOCOL.md
git commit -m "feat(paper): add tie-break consensus runner and dry-run path"
```

---

### Task 6: Live pilot (small) + paper walkthrough dump

**Files:**
- Create (run artifacts, usually not committed raw): `experiments/paper/results/tiebreak-non-nonsense/<run_id>/`
- Create: `experiments/paper/results/tiebreak-nonsense/<run_id>/`
- Optionally commit aggregates only if small

- [ ] **Step 1: Confirm Ollama has the pinned consensus model**

```bash
ollama list | grep -F "$(python - <<'PY'
import yaml
from pathlib import Path
print(yaml.safe_load(Path('experiments/paper/configs/tiebreak-non-nonsense.yaml').read_text())['models']['consensus'])
PY
)"
```

- [ ] **Step 2: Live pilot `limit=3` on non-nonsense (includes apples if first)**

```bash
python -m experiments.paper.runners.run_tiebreak_consensus \
  --config experiments/paper/configs/tiebreak-non-nonsense.yaml --limit 3
```

Inspect records: apples case shows three candidates, consensus `observed`, `llm_invoked`, soft match vs expected.

- [ ] **Step 3: Live full runs for both experiment ids (no `--limit`)**

- [ ] **Step 4: Spot-check calibration** — `expect_llm_matched` rate; if exact cases show `llm_invoked=true`, fix candidates (accidental paraphrase) or validator.

- [ ] **Step 5: Commit aggregates + analysis notes update (not full JSONL if gitignored)**

```bash
git add experiments/paper/analysis/tiebreak_consensus.md experiments/paper/PROTOCOL.md
# add aggregate.csv/manifest.json if policy allows
git commit -m "docs(paper): record tie-break pilot/full-run operator notes"
```

---

## Spec coverage checklist

| Spec requirement | Task |
|------------------|------|
| Constructed dummies, clear expected | 2–3 |
| excerpt=None | 5 |
| Nonsense majority adopted | 2–3 families + metrics |
| Biology + general prompts | 4–5 |
| ~25/75 det/LLM mix | 2 (32 briefs, 8 det) |
| Baseline vs hybrid necessity | 5 |
| llm_invoked flag | 5 |
| Soft Jaccard ≥ 0.50 | 1 |
| One suite / two config filters | 3, 5 |
| Artifact contract | 5 |
| Subagents generate candidates from expected + majority/minority | 2–3 |

## Placeholder / consistency self-check

- Soft threshold constant `0.50` matches spec.
- Fixture size locked at 32 / 8 deterministic.
- Subagent prompt forbids changing `expected`.
- Runner condition ids: `no_consensus_pick_extractor_0`, `hybrid_consensus`.
- No Gemini/bias/ortholog work in this plan.
