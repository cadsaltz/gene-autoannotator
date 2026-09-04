# Design: Tie-break / consensus experiments (nonsense + non-nonsense)

Date: 2026-09-03  
Status: approved  
Owners: Caden  
Scope: `tiebreak-nonsense`, `tiebreak-non-nonsense` only  
Approach: **one shared fixture suite + one runner + two config filters**

## Goal

Show two related facts with the same constructed-case suite:

1. **Consensus is necessary for the best merge result** — a single dummy extractor (baseline) loses to hybrid consensus on the same candidates when the first extractor is wrong or incomplete.
2. **An LLM is a usable tie-breaker** — when exact majority rules cannot decide, the batch consensus LLM reconciles paraphrase / near-agreement into one answer that matches a labeled expected majority meaning (including made-up nonsense words when that is the majority).

This suite does **not** prove excerpt-grounded reliability or full-pipeline correctness. It proves **reconciliation under trust-the-extractors**.

## Decisions locked

| Decision | Choice |
|----------|--------|
| Evidence source | Programmatic dummy extractor JSONs only (no PMC, no live extractors) |
| Excerpt | Always `excerpt=None` in `hybrid_section_consensus` (no excerpt gate) |
| Expected label | Every trial has one clear `expected` majority/reconciled answer for easy comparison |
| Nonsense policy | Majority made-up words **should be adopted** (claim A / trust extractors) |
| Domains | `biology` (existing batch consensus prompt + annotation fields) and `general` (new general merge prompt + neutral fields) |
| Case mix | ~20–30% deterministic (`expect_llm=false`); ~70–80% LLM path (`expect_llm=true`) |
| Packaging | One fixture file; configs filter by `case_family` / experiment id |
| Baseline arm | `no_consensus_pick_extractor_0` vs `hybrid_consensus` |
| Thin runner | Call existing `hybrid_section_consensus` + biology `batch_merger`; add general prompt helper only — no second annotation pipeline |
| Observability | Always record `llm_invoked` (bool) and provenance string (deterministic vs `llm_batch_merge` vs null) |

## Claim vs non-claim

| Proves | Does not prove |
|--------|----------------|
| Exact majority merge works without LLM | That majority gibberish is scientifically true |
| LLM paraphrase tie-break matches labeled expected | Excerpt-supported / hallucination rejection |
| Minority errors are overridden | Bias 1-vs-3 on real papers |
| Consensus beats “always take extractor 0” on necessity cases | Aggregation, retrieval, ortholog, cost at genome scale |
| Same mechanism on biology + general prompts | |

## What a trial is

**One trial = one constructed merge case** with three candidate objects and one labeled expected field value.

### Simplified general example (paper-friendly)

```text
majority / expected: apples are red and delicious

dummy extractor 1: apples are green and sour
dummy extractor 2: apples are red and sweet
dummy extractor 3: most apples are delicious, especialy the red ones

consensus response: <filled by run>
llm_invoked: true|false
```

Every fixture row must be writable in that shape for a human reader.

### Fixture schema (per case)

```json
{
  "case_id": "general-apples-paraphrase-001",
  "domain": "general",
  "case_family": "paraphrase_majority",
  "experiment_tags": ["tiebreak-non-nonsense"],
  "field_key": "answer",
  "expect_llm": true,
  "expected": "apples are red and delicious",
  "candidates": [
    {"answer": "apples are green and sour"},
    {"answer": "apples are red and sweet"},
    {"answer": "most apples are delicious, especialy the red ones"}
  ],
  "notes": "Extractor 0 is the minority error; 1 and 3 share red/delicious meaning."
}
```

Biology cases use the same shape with annotation field keys (e.g. `function`) and full-ish candidate objects so the existing biology batch schema accepts them (dummy `gene_id` / `name` allowed as fixed identity).

### Case families

| Family | `expect_llm` | Role |
|--------|--------------|------|
| `exact_majority` | false | Two identical values, one different → deterministic majority |
| `exact_majority_nonsense` | false | Same with made-up words → adopt gibberish majority |
| `paraphrase_majority` | true | Near-paraphrases share meaning; one outlier → LLM merge |
| `paraphrase_majority_nonsense` | true | Near-paraphrase nonsense majority → adopt majority gibberish via LLM |
| `minority_error` | false or true | Clear majority; extractor 0 is wrong (necessity vs baseline) |
| `hard_split_null` | true or false | Three incompatible values → expect `null`, no invention |

Target mix across the full suite: **~25%** `expect_llm=false`, **~75%** `expect_llm=true`. Both domains represented in both buckets.

`tiebreak-nonsense` config selects families whose majority/expected is made-up words.  
`tiebreak-non-nonsense` selects real-language / biology paraphrase and exact cases (including the apples-style example).

## Conditions

| Condition id | Behavior |
|--------------|----------|
| `no_consensus_pick_extractor_0` | Observed = `candidates[0][field_key]` |
| `hybrid_consensus` | `hybrid_section_consensus(..., excerpt=None, batch_merger=...)` |

Optional debug-only (not required for paper aggregates): `deterministic_only` with `batch_merger=None`.

## Prompts and schemas

| Domain | Prompt | Fields |
|--------|--------|--------|
| `biology` | Existing `BATCH_CONSENSUS_PROMPT` | Existing annotation field specs |
| `general` | New general merge prompt with the same rules: candidates only, majority/paraphrase, no invention, null on irreconcilable conflict, **no source text** | Minimal: at least `answer` (string); optional `tags` (array), `flag` (bool) for a few cases |

General prompt lives as an experiment helper (or small addition next to the biology prompt) used only by the tie-break runner’s `batch_merger` for `domain=general`.

## Matching expected (operational)

LLM wording will not always equal the fixture string character-for-character.

| Metric | Definition |
|--------|------------|
| `match_exact` | Whitespace/case-normalized equality to `expected` (or both null) |
| `match_soft` | Token Jaccard ≥ **0.50** vs `expected` (booleans/arrays: exact after normalize) |
| `invention` | Non-null output not traceable to any candidate under existing consensus traceability rules |
| `llm_invoked` | Hybrid reported LLM batch call count > 0 for that field path (or provenance `llm_batch_merge`) |

**Primary paper rates** use `match_soft` (and exact as a secondary column).  
**Necessity:** on cases where extractor 0 ≠ expected (soft), consensus soft-match rate minus baseline soft-match rate.

Null expected: soft/exact match only if observed is null; invention = false.

## Runner

Single module, e.g. `experiments/paper/runners/run_tiebreak_consensus.py`:

1. Load YAML config (`experiment_id`, model tag, fixture path, family/tag filter).
2. Load fixture cases; filter to this experiment.
3. For each case × condition, run baseline or hybrid; force `excerpt=None`.
4. Write `results/<experiment_id>/<run_id>/manifest.json`, `records.jsonl`, `aggregate.csv`.

### records.jsonl (minimum fields)

- `case_id`, `domain`, `case_family`, `field_key`, `condition`
- `candidates`, `expected`, `observed`
- `llm_invoked`, `provenance`
- `match_exact`, `match_soft`, `invention`
- `expect_llm`, `expect_llm_matched` (`llm_invoked == expect_llm`)

### aggregate.csv (minimum columns)

- counts and rates overall and by `domain`, `case_family`, `expect_llm`
- `consensus_match_soft_rate`, `baseline_match_soft_rate`, `necessity_delta`
- `llm_invoked_rate`, `expect_llm_calibration_rate` (fraction where `llm_invoked == expect_llm`)
- `invention_rate`
- `nonsense_majority_adoption_rate` (nonsense families only, consensus arm)

## Configs

- `configs/tiebreak-nonsense.yaml` — filter nonsense families; pin consensus model tag; point at shared fixture.
- `configs/tiebreak-non-nonsense.yaml` — filter non-nonsense families; same fixture and model.

Shared fixture path (planned): `fixtures/constructed/tiebreak_consensus_v1.json`.

## Sample size

- v1 suite: on the order of **20–40** cases total (enough for a table + a few paper walkthroughs), not 100+.
- Exact list is authored in the fixture file before scoring.
- Include the apples paraphrase case as a named paper example.

## Paper write-up shape

> In *N* constructed consensus trials (*n_det* deterministic, *n_llm* LLM tie-break), hybrid consensus matched the labeled expected answer in *X/N* (soft). Taking only extractor 0 matched in *Y/N* (necessity gap *X−Y*). LLM was invoked in *Z* trials (target ~75% of suite). Majority nonsense was adopted in *…*. Figure: apples (or biology) candidates → consensus → `llm_invoked` flag.

## Out of scope

- Bias / split / cost cluster changes
- Gemini, GO-distance, ortholog, false-cognates, relevance diminishing returns
- Changing production consensus to require excerpts
- Human labeling (expected is by construction)

## Implementation order (after spec approval)

1. Author `tiebreak_consensus_v1` fixture (biology + general; ~25/75 mix; apples example included).
2. Update configs + `PROTOCOL.md` registry status.
3. Implement general merge prompt helper + thin runner.
4. Dry-run on a few cases; then full filtered runs for both experiment ids.
5. Analysis notes under `analysis/` from aggregates only.
