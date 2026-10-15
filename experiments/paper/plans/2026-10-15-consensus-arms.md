# Consensus Arms Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build experiment-only post-processors and runners that score arms A / B / B-ref / C / D against labeled needles, producing one spreadsheet per arm, so a crowd decision step can be compared to gemma4:12b alone without touching production deployment code.

**Architecture:** Extractors run once (Phase 1 reuses saved `mixed20_model_spread_15k` outputs; Phase 3 runs a fresh extraction). Each arm is a pure decision-step function over those candidates. A sequential CLI runs arms one at a time into `results/consensus-arms/<run_id>/arm_<name>/` with records + a team-review spreadsheet. Production `autoannotation/consensus.py` and worker/fleet code are never modified.

**Tech Stack:** Python 3.11+, pytest, PyYAML, openpyxl, Ollama (`gemma4:26b` for B/C), optional local classifiers (MiniCheck / HHEM / Bespoke-MiniCheck-7B) for D.

**Design spec:** `experiments/paper/specs/2026-10-07-consensus-arms-design.md`

## Global Constraints

- **Branch:** all work lands on `experiments`. Do not merge to master as part of this plan.
- **No deployment:** never edit `worker/`, `deploy/`, production `autoannotation/consensus.py` merge path, or `worker.env` defaults for the live annotator. Experiment code may *call* existing `hybrid_section_consensus` / `ollama_chat` helpers.
- **Shared extraction:** arms differ only after extraction. Phase 1 must not re-call extractors.
- **Judge model for B and C:** `gemma4:26b` (same tag in both; isolates excerpt + vote-gate, not model size).
- **B trio:** `gemma4:12b` + `phi4:14b` + `dolphin3:8b`. **B-ref trio:** `gemma4:12b` + `phi4:14b` + `granite4.2:8b`.
- **C / D:** no `ceil(n/2)` vote gate; every non-null candidate reaches the judge/classifier.
- **C output:** select candidate values verbatim; no rewriting.
- **D claims:** deterministic templates only; no LLM rewrite of claims.
- **Success bar:** beat A only with more needles found AND fewer false positives on the held-out test split.
- **Artifacts:** `experiments/paper/results/consensus-arms/<run_id>/arm_<name>/{manifest.json,records.jsonl,team_review.xlsx}` plus a run-level `compare/` summary after all arms finish.
- **Out of scope:** prompt changes, keyword windows, gene-mention gating, new extractor models, production consensus refactor, Jev API.

---

## File map (target)

| Path | Role |
|------|------|
| `experiments/paper/runners/consensus_arms_io.py` | Load model-spread records; map model→extractor letter; load needle labels |
| `experiments/paper/runners/consensus_arms_claims.py` | Deterministic claim builder for arm D |
| `experiments/paper/runners/consensus_arms_decide.py` | Arm A/B/C/D decision functions |
| `experiments/paper/runners/consensus_arms_judge_c.py` | Excerpt-aware verbatim-select judge (arm C only) |
| `experiments/paper/runners/consensus_arms_classifiers.py` | MiniCheck / HHEM / Bespoke-MiniCheck adapters + skip for Nimble |
| `experiments/paper/runners/run_consensus_arms.py` | Sequential CLI: `--arm`, `--records`, `--labels`, `--out` |
| `experiments/paper/scripts/build_consensus_arms_spreadsheet.py` | One workbook per arm (excerpt + candidates + arm output + flags) |
| `experiments/paper/scripts/compare_consensus_arms.py` | Scoreboard + A-vs-arm needle diffs across finished arm dirs |
| `experiments/paper/configs/consensus-arms-pilot.yaml` | Phase 1 paths, models, classifier list |
| `experiments/paper/configs/consensus-arms-phase3.yaml` | Phase 3 extraction + arms (later) |
| `experiments/paper/analysis/consensus_arms.md` | Operator runbook (sequential commands) |
| `experiments/paper/tests/test_consensus_arms_io.py` | Record/label loading |
| `experiments/paper/tests/test_consensus_arms_claims.py` | Claim templates |
| `experiments/paper/tests/test_consensus_arms_decide.py` | A/B/C/D decision logic with mocks |
| `experiments/paper/tests/test_consensus_arms_judge_c.py` | Verbatim selection + prompt shape |
| `experiments/paper/tests/test_consensus_arms_runner_dry.py` | Dry sequential run over tiny fixture |

Pilot inputs (read-only; copy or symlink under results if needed):

- Records: `/home/caden-saltzberg/Downloads/model_spread_15k/records.jsonl` (or `experiments/paper/results/model_spread_15k/` copy)
- Labels: `experiments/paper/results/model_spread_15k/labels/`

Model letter map from the pilot manifest:

| Letter | Model |
|--------|-------|
| A | gemma4:12b |
| D | dolphin3:8b |
| F | phi4:14b |
| G | granite4.2:8b |

---

### Task 1: IO helpers (load records + labels)

**Files:**
- Create: `experiments/paper/runners/consensus_arms_io.py`
- Create: `experiments/paper/tests/test_consensus_arms_io.py`

**Interfaces:**
- Consumes: `records.jsonl` trial_observable rows; label JSONs under `labels/`
- Produces:
  - `MODEL_LETTER = {"gemma4:12b": "A", "dolphin3:8b": "D", "phi4:14b": "F", "granite4.2:8b": "G", ...}`
  - `load_biology_trials(records_path: Path) -> list[dict]` — biology `trial_observable` only
  - `extractor_outputs_by_model(trial: dict) -> dict[str, dict]` — `{model: output_json}`
  - `load_labels(labels_dir: Path) -> dict[str, dict]` — keyed by packet filename stem matching `trial_id` with `#` → `_`
  - `packet_stem(trial_id: str) -> str`

- [ ] **Step 1: Write the failing tests**

```python
# experiments/paper/tests/test_consensus_arms_io.py
from pathlib import Path
import json
from experiments.paper.runners.consensus_arms_io import (
    packet_stem,
    load_biology_trials,
    extractor_outputs_by_model,
    load_labels,
)

def test_packet_stem_replaces_hash():
    assert packet_stem("t010_b0090_PMC6327494_results#2") == "t010_b0090_PMC6327494_results_2"

def test_load_biology_skips_general(tmp_path: Path):
    rows = [
        {"record_type": "trial_observable", "trial_pool": "general", "trial_id": "g1",
         "outputs": {}, "condition_metrics": {}},
        {"record_type": "trial_observable", "trial_pool": "biology", "trial_id": "b1",
         "outputs": {"extractor_A": {"function": None}},
         "condition_metrics": {"extractor_A": {"model": "gemma4:12b"}}},
        {"record_type": "manifest", "trial_pool": "biology"},
    ]
    p = tmp_path / "records.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    trials = load_biology_trials(p)
    assert len(trials) == 1 and trials[0]["trial_id"] == "b1"

def test_extractor_outputs_by_model_maps_letters():
    trial = {
        "outputs": {"extractor_A": {"function": "x"}, "extractor_D": {"function": "y"},
                    "consensus_D": {"function": None}},
        "condition_metrics": {
            "extractor_A": {"model": "gemma4:12b"},
            "extractor_D": {"model": "dolphin3:8b"},
            "consensus_D": {"model": "qwen3.5:9b"},
        },
    }
    by_m = extractor_outputs_by_model(trial)
    assert by_m["gemma4:12b"]["function"] == "x"
    assert by_m["dolphin3:8b"]["function"] == "y"
    assert "qwen3.5:9b" not in by_m
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest experiments/paper/tests/test_consensus_arms_io.py -v`  
Expected: FAIL (import error / missing module)

- [ ] **Step 3: Implement `consensus_arms_io.py`**

```python
# experiments/paper/runners/consensus_arms_io.py
from __future__ import annotations
import json
import re
from pathlib import Path
from typing import Any

MODEL_LETTER = {
    "gemma4:12b": "A",
    "qwen3.5:9b": "B",
    "mistral-nemo:12b": "C",
    "dolphin3:8b": "D",
    "ministral-3:14b": "E",
    "phi4:14b": "F",
    "granite4.2:8b": "G",
    "llama3.1:8b": "H",
    "rnj-1:8b": "I",
}

def packet_stem(trial_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", trial_id)

def load_biology_trials(records_path: Path) -> list[dict[str, Any]]:
    out = []
    with Path(records_path).open() as fh:
        for line in fh:
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("record_type") == "trial_observable" and row.get("trial_pool") == "biology":
                out.append(row)
    return out

def extractor_outputs_by_model(trial: dict[str, Any]) -> dict[str, dict[str, Any]]:
    by_model: dict[str, dict[str, Any]] = {}
    for cond, metrics in (trial.get("condition_metrics") or {}).items():
        if not str(cond).startswith("extractor_"):
            continue
        model = metrics["model"]
        by_model[model] = trial["outputs"][cond]
    return by_model

def load_labels(labels_dir: Path) -> dict[str, dict[str, Any]]:
    labels: dict[str, dict[str, Any]] = {}
    for path in Path(labels_dir).glob("t*.json"):
        labels[path.stem] = json.loads(path.read_text())
    return labels
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest experiments/paper/tests/test_consensus_arms_io.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add experiments/paper/runners/consensus_arms_io.py experiments/paper/tests/test_consensus_arms_io.py
git commit -m "feat(paper): IO helpers for consensus-arms pilot records and labels"
```

---

### Task 2: Arm A + Arm B decision (reuse production hybrid)

**Files:**
- Create: `experiments/paper/runners/consensus_arms_decide.py`
- Create: `experiments/paper/tests/test_consensus_arms_decide.py`

**Interfaces:**
- Consumes: `autoannotation.consensus.hybrid_section_consensus`, `autoannotation.llms.LLMHandler` (or a callable `batch_merger`)
- Produces:
  - `TRIO_B = ("gemma4:12b", "phi4:14b", "dolphin3:8b")`
  - `TRIO_BREF = ("gemma4:12b", "phi4:14b", "granite4.2:8b")`
  - `decide_arm_a(by_model: dict) -> dict` — copy of gemma4:12b output
  - `decide_arm_b(by_model, *, models: tuple[str, ...], batch_merger, expected_gene_id, expected_name, organism_profile, field_defs_profile, excerpt) -> tuple[dict, dict, int]`
    - Calls `hybrid_section_consensus(..., excerpt=excerpt, batch_merger=batch_merger)` with the **production** vote gate (unchanged). Excerpt is passed only for the post-merge word-overlap validator, matching production. The merger prompt itself must still be the production `BATCH_CONSENSUS_PROMPT` (no excerpt text).

- [ ] **Step 1: Write the failing tests**

```python
# experiments/paper/tests/test_consensus_arms_decide.py
from experiments.paper.runners.consensus_arms_decide import decide_arm_a, decide_arm_b, TRIO_B

def test_arm_a_is_gemma_passthrough():
    by_model = {
        "gemma4:12b": {"function": "real", "functional_category": None},
        "dolphin3:8b": {"function": "hallucination", "functional_category": None},
    }
    out = decide_arm_a(by_model)
    assert out == by_model["gemma4:12b"]
    assert out is not by_model["gemma4:12b"]  # copy

def test_arm_b_calls_hybrid_with_trio_candidates(monkeypatch):
    calls = {}
    def fake_hybrid(candidates, **kwargs):
        calls["candidates"] = candidates
        calls["kwargs"] = kwargs
        return {"function": "merged"}, {"function": "majority"}, 1

    monkeypatch.setattr(
        "experiments.paper.runners.consensus_arms_decide.hybrid_section_consensus",
        fake_hybrid,
    )
    by_model = {
        "gemma4:12b": {"function": "a", "name": "murG"},
        "phi4:14b": {"function": "b", "name": "murG"},
        "dolphin3:8b": {"function": "c", "name": "murG"},
        "granite4.2:8b": {"function": "should-not-appear", "name": "murG"},
    }
    merged, prov, n = decide_arm_b(
        by_model,
        models=TRIO_B,
        batch_merger=lambda *_: {},
        expected_gene_id="b0090",
        expected_name="murG",
        organism_profile=None,
        field_defs_profile=None,
        excerpt="excerpt text",
    )
    assert [c["function"] for c in calls["candidates"]] == ["a", "b", "c"]
    assert calls["kwargs"]["excerpt"] == "excerpt text"
    assert merged["function"] == "merged"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest experiments/paper/tests/test_consensus_arms_decide.py::test_arm_a_is_gemma_passthrough experiments/paper/tests/test_consensus_arms_decide.py::test_arm_b_calls_hybrid_with_trio_candidates -v`  
Expected: FAIL (missing module)

- [ ] **Step 3: Implement A and B in `consensus_arms_decide.py`**

```python
# experiments/paper/runners/consensus_arms_decide.py (partial)
from __future__ import annotations
import copy
from typing import Any, Callable
from autoannotation.consensus import hybrid_section_consensus

TRIO_B = ("gemma4:12b", "phi4:14b", "dolphin3:8b")
TRIO_BREF = ("gemma4:12b", "phi4:14b", "granite4.2:8b")
JUDGE_MODEL = "gemma4:26b"

def decide_arm_a(by_model: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return copy.deepcopy(by_model["gemma4:12b"])

def decide_arm_b(
    by_model: dict[str, dict[str, Any]],
    *,
    models: tuple[str, ...],
    batch_merger: Callable,
    expected_gene_id: str | None,
    expected_name: str,
    organism_profile,
    field_defs_profile,
    excerpt: str | None,
) -> tuple[dict[str, Any], dict[str, str], int]:
    candidates = [by_model[m] for m in models]
    return hybrid_section_consensus(
        candidates,
        excerpt=excerpt,
        expected_gene_id=expected_gene_id,
        expected_name=expected_name,
        organism_profile=organism_profile,
        field_defs_profile=field_defs_profile,
        batch_merger=batch_merger,
    )
```

Provide a helper used by the runner to build the production-style batch_merger via `LLMHandler._ollama_batch_consensus_merge` with `model=JUDGE_MODEL` (do not change `BATCH_CONSENSUS_PROMPT`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest experiments/paper/tests/test_consensus_arms_decide.py::test_arm_a_is_gemma_passthrough experiments/paper/tests/test_consensus_arms_decide.py::test_arm_b_calls_hybrid_with_trio_candidates -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add experiments/paper/runners/consensus_arms_decide.py experiments/paper/tests/test_consensus_arms_decide.py
git commit -m "feat(paper): consensus-arms A passthrough and B hybrid decision"
```

---

### Task 3: Arm C excerpt-aware verbatim judge

**Files:**
- Create: `experiments/paper/runners/consensus_arms_judge_c.py`
- Modify: `experiments/paper/runners/consensus_arms_decide.py` (add `decide_arm_c`)
- Create: `experiments/paper/tests/test_consensus_arms_judge_c.py`
- Modify: `experiments/paper/tests/test_consensus_arms_decide.py`

**Interfaces:**
- Consumes: `autoannotation.llms.ollama_chat`, `parse_response_json`, organism field specs
- Produces:
  - `ARM_C_JUDGE_PROMPT` — includes `target_gene`, `excerpt`, `candidates_json`, `field_list`
  - `build_arm_c_prompt(...) -> str`
  - `select_supported_verbatim(judge_payload, candidates, field_keys) -> dict` — keep only values that appear in some candidate (exact or soft Jaccard ≥ 0.85 for strings; set equality for arrays)
  - `decide_arm_c(by_model, *, models, judge_fn, expected_gene_id, expected_name, excerpt, fields) -> dict`
    - **No vote gate:** all candidates for `models` are sent.
    - Judge returns per-field selected value or null.
    - Post-filter rejects inventions not present in candidates.

Prompt rules (must appear in `ARM_C_JUDGE_PROMPT`):

```
Using ONLY the excerpt and the candidate values, for each field select the candidate value
that the excerpt supports about gene {gene_name} ({gene_id}), or null.

Rules:
- Return JSON with exactly the listed field keys.
- Select a value VERBATIM from one of the candidates. Do not rewrite or invent wording.
- If multiple candidates are supported, prefer the one that best matches the excerpt; if tied, prefer the shorter value.
- Use null when the excerpt does not support any candidate for that field about this gene.
- Ignore candidates that attribute another gene's facts to this gene.
```

- [ ] **Step 1: Write the failing tests**

```python
# experiments/paper/tests/test_consensus_arms_judge_c.py
from experiments.paper.runners.consensus_arms_judge_c import (
    build_arm_c_prompt,
    select_supported_verbatim,
)

def test_prompt_includes_excerpt_and_gene():
    prompt = build_arm_c_prompt(
        gene_id="b0090",
        gene_name="murG",
        excerpt="murG (b0090) is in the peptidoglycan trail.",
        candidates=[{"function": "MurG participates in peptidoglycan biosynthesis."}],
        field_keys=["function"],
    )
    assert "murG" in prompt and "b0090" in prompt
    assert "peptidoglycan trail" in prompt
    assert "VERBATIM" in prompt.upper() or "verbatim" in prompt

def test_select_rejects_invention():
    cands = [{"function": "MurG participates in peptidoglycan biosynthesis."}]
    payload = {"function": "MurG is a transcription factor."}
    out = select_supported_verbatim(payload, cands, ["function"])
    assert out["function"] is None

def test_select_keeps_candidate_string():
    cands = [{"function": "MurG participates in peptidoglycan biosynthesis."}]
    payload = {"function": "MurG participates in peptidoglycan biosynthesis."}
    out = select_supported_verbatim(payload, cands, ["function"])
    assert out["function"] == cands[0]["function"]
```

```python
# add to test_consensus_arms_decide.py
def test_arm_c_no_vote_gate_sends_all_candidates():
    seen = {}
    def judge_fn(candidates, field_keys, excerpt, gene_id, gene_name):
        seen["n"] = len(candidates)
        return {k: candidates[0].get(k) for k in field_keys}
    by_model = {
        "gemma4:12b": {"function": "a"},
        "phi4:14b": {"function": None},
        "dolphin3:8b": {"function": "c"},
    }
    from experiments.paper.runners.consensus_arms_decide import decide_arm_c, TRIO_B
    decide_arm_c(
        by_model, models=TRIO_B, judge_fn=judge_fn,
        expected_gene_id="b0090", expected_name="murG",
        excerpt="text", field_keys=["function"],
    )
    assert seen["n"] == 3
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest experiments/paper/tests/test_consensus_arms_judge_c.py experiments/paper/tests/test_consensus_arms_decide.py::test_arm_c_no_vote_gate_sends_all_candidates -v`  
Expected: FAIL

- [ ] **Step 3: Implement judge_c + `decide_arm_c`**

Implement `select_supported_verbatim` using `autoannotation.consensus.token_jaccard` with threshold 0.85 for strings; for arrays require the returned list to equal one candidate list (order-insensitive). Booleans must equal a candidate boolean.

Wire `judge_fn` in the runner to call Ollama with `model=JUDGE_MODEL`, JSON schema for the field keys, and `ARM_C_JUDGE_PROMPT`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest experiments/paper/tests/test_consensus_arms_judge_c.py experiments/paper/tests/test_consensus_arms_decide.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add experiments/paper/runners/consensus_arms_judge_c.py experiments/paper/runners/consensus_arms_decide.py experiments/paper/tests/test_consensus_arms_judge_c.py experiments/paper/tests/test_consensus_arms_decide.py
git commit -m "feat(paper): arm C excerpt-aware verbatim consensus judge"
```

---

### Task 4: Arm D claim builder

**Files:**
- Create: `experiments/paper/runners/consensus_arms_claims.py`
- Create: `experiments/paper/tests/test_consensus_arms_claims.py`

**Interfaces:**
- Produces:
  - `Claim = TypedDict` with `field`, `text`, `source_model`, `source_value`, `claim_index`
  - `build_claims_for_candidate(output, *, organism, gene_id, gene_name, model) -> list[Claim]`
  - `build_claims_for_trio(by_model, models, **meta) -> list[Claim]`

Templates:

```python
PREFIX = f"In {organism}, gene {gene_name} ({gene_id})"
# function: for each non-empty sentence s in function:
#   f"{PREFIX}: {s}"
# functional_category tag t:
#   f"{PREFIX} is involved in {t}."
# drug_susc_impact / infection_impact:
#   f"{PREFIX} drug susceptibility impact: {value}" / infection...
# essential_in_vitro / essential_in_vivo bool:
#   f"{PREFIX} is {'essential' if value else 'not essential'} in vitro."
```

- [ ] **Step 1: Write the failing tests**

```python
from experiments.paper.runners.consensus_arms_claims import build_claims_for_candidate

def test_function_splits_sentences():
    claims = build_claims_for_candidate(
        {"function": "Does X. Also does Y.", "functional_category": None},
        organism="Escherichia coli",
        gene_id="b0090",
        gene_name="murG",
        model="gemma4:12b",
    )
    texts = [c["text"] for c in claims]
    assert any("Does X." in t for t in texts)
    assert any("Also does Y." in t for t in texts)
    assert all("murG" in t and "b0090" in t for t in texts)

def test_category_one_claim_per_tag():
    claims = build_claims_for_candidate(
        {"function": None, "functional_category": ["peptidoglycan biosynthesis", "cell wall"]},
        organism="Escherichia coli",
        gene_id="b0090",
        gene_name="murG",
        model="phi4:14b",
    )
    assert len(claims) == 2
    assert claims[0]["field"] == "functional_category"
```

- [ ] **Step 2: Run to verify fail → implement → pass → commit**

```bash
git add experiments/paper/runners/consensus_arms_claims.py experiments/paper/tests/test_consensus_arms_claims.py
git commit -m "feat(paper): deterministic claim builder for consensus-arms D"
```

---

### Task 5: Arm D classifiers + decide_arm_d

**Files:**
- Create: `experiments/paper/runners/consensus_arms_classifiers.py`
- Modify: `experiments/paper/runners/consensus_arms_decide.py`
- Modify: `experiments/paper/tests/test_consensus_arms_decide.py`
- Create: `experiments/paper/tests/test_consensus_arms_classifiers.py`

**Interfaces:**
- Produces:
  - `ClassifierScore = TypedDict` with `claim_text`, `score: float`, `backend: str`
  - `score_claim(backend: str, claim: str, excerpt: str) -> float` — backends: `minicheck_ft5`, `hhem`, `bespoke_minicheck_7b`; `nimble` raises `ClassifierSkipped`
  - `slice_excerpt(excerpt: str, max_chars: int = 6000, stride: int = 3000) -> list[str]` — overlapping slices; score = max over slices
  - `decide_arm_d(by_model, *, models, claims, scores_by_claim_id, threshold: float) -> dict`
    - Per field: keep only claim pieces that pass threshold; reassemble strings (join sentences) / arrays (kept tags) / booleans (majority of passing bool claims or null)

**Classifier loading (lazy, experiment-only):**

| backend | How |
|---------|-----|
| `minicheck_ft5` | `MiniCheck(model_name='flan-t5-large')` from `minicheck` package if installed |
| `hhem` | `transformers` pipeline / Vectara HHEM-2.1-open |
| `bespoke_minicheck_7b` | MiniCheck Bespoke-7B with 4-bit if VRAM allows; else skip with reason |
| `nimble` | skip by default (`ClassifierSkipped("quantization deferred")`) |

Unit tests mock `score_claim`; do not download models in CI.

- [ ] **Step 1: Tests for slicing + reassembly with mock scores**

```python
def test_decide_arm_d_keeps_passing_tags_only():
    from experiments.paper.runners.consensus_arms_decide import decide_arm_d
    by_model = {
        "gemma4:12b": {"functional_category": ["peptidoglycan biosynthesis", "made up pathway"]},
        "phi4:14b": {"functional_category": None},
        "dolphin3:8b": {"functional_category": None},
    }
    # claims[0] supported, claims[1] not — scores keyed by claim id
    ...
    out = decide_arm_d(...)
    assert out["functional_category"] == ["peptidoglycan biosynthesis"]
```

- [ ] **Step 2: Implement → pass → commit**

```bash
git commit -m "feat(paper): arm D classifier adapters and thresholded reassembly"
```

---

### Task 6: Sequential runner + config (Phase 1 pilot)

**Files:**
- Create: `experiments/paper/runners/run_consensus_arms.py`
- Create: `experiments/paper/configs/consensus-arms-pilot.yaml`
- Create: `experiments/paper/tests/test_consensus_arms_runner_dry.py`
- Create: `experiments/paper/analysis/consensus_arms.md`

**Interfaces:**
- CLI:

```bash
PYTHONPATH=. python -m experiments.paper.runners.run_consensus_arms \
  --config experiments/paper/configs/consensus-arms-pilot.yaml \
  --arm A \
  --run-id pilot_$(date +%Y%m%d) \
  [--dry-run]
```

- `--arm` one of: `A`, `B`, `B-ref`, `C`, `D:minicheck_ft5`, `D:hhem`, `D:bespoke_minicheck_7b`
- Writes `experiments/paper/results/consensus-arms/<run_id>/arm_<safe_name>/`:
  - `manifest.json` — arm, models, judge/classifier, git sha, source records path, duration
  - `records.jsonl` — one row per biology trial: `trial_id`, `excerpt_text`, `candidates`, `arm_output`, `decision_metrics` (`llm_duration_sec` / `classifier_duration_sec`)
- Arms run **sequentially** (one process, one arm per invocation) so Ollama/GPU is not shared across arms.
- Resume: skip trials already present in that arm's `records.jsonl` (match `trial_id`).

**Config sketch:**

```yaml
experiment_id: consensus-arms-pilot
source_records: /home/caden-saltzberg/Downloads/model_spread_15k/records.jsonl
labels_dir: experiments/paper/results/model_spread_15k/labels
judge_model: gemma4:26b
trio_b: [gemma4:12b, phi4:14b, dolphin3:8b]
trio_bref: [gemma4:12b, phi4:14b, granite4.2:8b]
classifiers: [minicheck_ft5, hhem, bespoke_minicheck_7b]
# D threshold tuned later; pilot default:
d_threshold: 0.5
```

- [ ] **Step 1: Dry-run test with tiny jsonl + mock judge/classifier**

```python
def test_dry_run_arm_a_writes_records(tmp_path, monkeypatch):
    # write 2 biology trials into tmp records
    # monkeypatch decide functions if needed
    # invoke main with --arm A --dry-run --out tmp_path
    # assert manifest + 2 records
```

- [ ] **Step 2: Implement runner + config + analysis runbook with exact sequential commands**

Runbook must list:

```bash
# Phase 1 — run arms one after another on sch
for ARM in A B B-ref C D:minicheck_ft5 D:hhem D:bespoke_minicheck_7b; do
  PYTHONPATH=. python -m experiments.paper.runners.run_consensus_arms \
    --config experiments/paper/configs/consensus-arms-pilot.yaml \
    --arm "$ARM" --run-id pilot_model_spread_15k
done
```

- [ ] **Step 3: Commit**

```bash
git commit -m "feat(paper): sequential consensus-arms pilot runner and config"
```

---

### Task 7: Per-arm spreadsheet + compare script

**Files:**
- Create: `experiments/paper/scripts/build_consensus_arms_spreadsheet.py`
- Create: `experiments/paper/scripts/compare_consensus_arms.py`
- Create: `experiments/paper/tests/test_consensus_arms_spreadsheet.py`

**Spreadsheet (one file per arm):** reuse patterns from `build_team_review_spreadsheet.py` and the needle overlay from `experiments/paper/results/model_spread_15k/annotate_workbook.py`, but scoped to:

- Excerpt (with needle highlights from labels when present)
- The three extractor outputs for that arm's trio
- Arm decision output
- Column G flags vs labels (✔ / ◐ / ✖ / ○ / ✓) — **no emoji** other than those symbols

CLI:

```bash
PYTHONPATH=. python experiments/paper/scripts/build_consensus_arms_spreadsheet.py \
  --arm-dir experiments/paper/results/consensus-arms/pilot_model_spread_15k/arm_A \
  --labels experiments/paper/results/model_spread_15k/labels \
  --out ~/Downloads/consensus_arms_pilot_arm_A_team_review.xlsx
```

**Compare script:**

```bash
PYTHONPATH=. python experiments/paper/scripts/compare_consensus_arms.py \
  --run-dir experiments/paper/results/consensus-arms/pilot_model_spread_15k \
  --labels experiments/paper/results/model_spread_15k/labels \
  --out experiments/paper/results/consensus-arms/pilot_model_spread_15k/compare/
```

Writes `scoreboard.csv` and `vs_A.md` with per-arm found/missed/FP and needle-by-needle diffs vs A.

- [ ] **Step 1: Test that builder creates a sheet with required row labels and does not alter excerpt text characters when highlighting**
- [ ] **Step 2: Implement → pass → commit**

```bash
git commit -m "feat(paper): per-arm spreadsheets and consensus-arms comparison report"
```

---

### Task 8: Wire Ollama batch merger for live B/C (integration smoke)

**Files:**
- Modify: `experiments/paper/runners/run_consensus_arms.py` (live path)
- Modify: `experiments/paper/analysis/consensus_arms.md`

**Requirements:**
- Load `worker.env` via existing experiment env loader (`apply_env_file` / paper common) so chunking env does not matter for this post-process; only Ollama host + model tags matter.
- B uses `LLMHandler` production merge path with `model=gemma4:26b`.
- C uses `consensus_arms_judge_c` Ollama call with `model=gemma4:26b`.
- Soft-fail per trial: on judge error, write `arm_output` all-null + error string in metrics; do not crash the arm run.
- Smoke on **one** trial before full pilot:

```bash
PYTHONPATH=. python -m experiments.paper.runners.run_consensus_arms \
  --config experiments/paper/configs/consensus-arms-pilot.yaml \
  --arm C --run-id smoke_c --max-trials 1
```

- [ ] **Step 1: Document smoke commands in analysis runbook**
- [ ] **Step 2: Commit**

```bash
git commit -m "docs(paper): consensus-arms live Ollama smoke path for B and C"
```

---

### Task 9: Phase 2 labeled-set builder (parallel track)

**Files:**
- Create: `experiments/paper/scripts/sample_consensus_arms_sections.py`
- Create: `experiments/paper/fixtures/gold/consensus_arms_v1/` (dir + README)
- Create: `experiments/paper/fixtures/constructed/CONSENSUS_ARMS_NEEDLE_PROMPT.md`

**Behavior:**
- Sample 120 sections from `fixtures/paper_snapshots/bias_cluster_v2.json` (40 per organism), seed fixed in config.
- Split papers 50/50 into `dev_papers.json` / `test_papers.json` (no paper on both sides).
- Write empty gold stubs: `{trial_id, gene_id, gene_name, profile_id, pmc_id, section, excerpt_text, fields: {}}`.
- Subagent prompt file: blind needle labeling (field, gold_value, gold_quote) with the same rubric as `labels/RUBRIC.md`.
- Double-label 15% for agreement; disagreements flagged `needs_human: true`.

- [ ] **Step 1: Unit test sampler sizes and paper-disjoint split**
- [ ] **Step 2: Implement → commit**

```bash
git commit -m "feat(paper): sample and gold stubs for consensus-arms Phase 2 labeled set"
```

---

### Task 10: Phase 3 extraction config (no production changes)

**Files:**
- Create: `experiments/paper/configs/consensus-arms-phase3.yaml`
- Modify: `experiments/paper/analysis/consensus_arms.md`

**Config:** points existing `run_bias_1_vs_3.py` at extractors `[gemma4:12b, phi4:14b, dolphin3:8b, granite4.2:8b]` and consensus placeholder (unused for arms post-process). After extraction finishes, re-run `run_consensus_arms.py` with `--records` pointing at the new run, `--labels` at Phase 2 gold, tune D threshold on **dev papers only**, freeze, then score **test**.

Do **not** change production worker defaults or deploy scripts.

- [ ] **Step 1: Add YAML + runbook section for Phase 3 sequential arms**
- [ ] **Step 2: Commit**

```bash
git commit -m "feat(paper): Phase 3 consensus-arms extraction config and runbook"
```

---

## Operator sequence (Phase 1 deliverable)

When Tasks 1–8 are done, the pilot is runnable:

```bash
# on sch, inside repo on experiments branch, venv active
cd ~/sch/gene-autoannotator
git checkout experiments
git pull   # if remote exists

RUN=pilot_model_spread_15k
for ARM in A B B-ref C D:minicheck_ft5 D:hhem D:bespoke_minicheck_7b; do
  PYTHONPATH=. python -m experiments.paper.runners.run_consensus_arms \
    --config experiments/paper/configs/consensus-arms-pilot.yaml \
    --arm "$ARM" --run-id "$RUN"
  PYTHONPATH=. python experiments/paper/scripts/build_consensus_arms_spreadsheet.py \
    --arm-dir experiments/paper/results/consensus-arms/$RUN/arm_${ARM//:/_} \
    --labels experiments/paper/results/model_spread_15k/labels \
    --out ~/Downloads/consensus_arms_${RUN}_arm_${ARM//:/_}_team_review.xlsx
done

PYTHONPATH=. python experiments/paper/scripts/compare_consensus_arms.py \
  --run-dir experiments/paper/results/consensus-arms/$RUN \
  --labels experiments/paper/results/model_spread_15k/labels \
  --out experiments/paper/results/consensus-arms/$RUN/compare/
```

Each arm gets its own spreadsheet; comparison lives under `compare/`.

---

## Spec coverage checklist

| Spec requirement | Task |
|------------------|------|
| Arm A gemma passthrough | 2 |
| Arm B current consensus, gemma4:26b | 2, 8 |
| Arm B-ref alternate trio | 2, 6 |
| Arm C no vote gate + excerpt + verbatim | 3 |
| Arm D classifiers + claim templates | 4, 5 |
| Sequential per-arm runs + resume | 6 |
| Per-arm spreadsheet | 7 |
| Compare vs A scoreboard | 7 |
| Phase 1 uses saved extractors | 1, 6 |
| Phase 2 labeled set | 9 |
| Phase 3 extraction config | 10 |
| No production/deployment edits | Global Constraints |

---

## Self-review notes

- No production `consensus.py` / worker edits; B reuses hybrid via import only.
- Arm C invention filter prevents judge rewriting from counting as grounded.
- D threshold tuning is Phase 3 / leave-one-paper-out in pilot — pilot is go/no-go, not the paper result.
- Spreadsheet path matches the user's request: one workbook per arm, then compare.
