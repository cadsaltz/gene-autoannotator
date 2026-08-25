# Paper experiment protocol

Living document. Nothing here is final until the paper draft locks a claim.
Every experiment maps a **claim** → **conditions** → **metrics** → **artifacts**.

## Thesis (working)

Published but unaggregated gene function information can be reliably aggregated
with LLMs using a wisdom-of-crowds approach. The system should be shown to be:

- **Reliable** — reduces bias/hallucination relative to a single-model baseline
- **Useful** — produces curator-usable, evidence-linked annotations
- **Automable / scalable** — runnable from public data across genes/organisms

## Artifact contract (all experiments)

Each run writes:

1. **Manifest** (`results/<experiment_id>/<run_id>/manifest.json`)
   - git commit SHA, config id, model tags, input fixture hashes, timestamp, host notes
2. **Per-item records** (`.../records.jsonl`)
   - one row per decision unit (typically gene × field × condition)
   - include intermediates needed for the claim (per-extractor outputs, consensus, baseline)
3. **Aggregate table** (`.../aggregate.csv` and/or `aggregate.json`)
   - numbers that can become paper tables
4. **Analysis entrypoint** under `analysis/` regenerates figures/tables from aggregates only

If a paper cell cannot be traced to a JSONL row and a frozen config, the claim is not ready.

## Shared rules

- Freeze inputs across arms of a contrast (same genes, same paper text snapshot when possible).
- Prefer field-level units of analysis over whole-gene vibes.
- Pin exact model tags / API model ids in configs.
- Pre-register gene/paper sets in `fixtures/` before scoring outcomes.
- Separate **quality** metrics from **cost** metrics; report both when claiming benefit.
- Be explicit about *n* and selection criteria.

## Experiment registry

Status: `planned` | `fixtures-ready` | `runnable` | `analyzed` | `paper-locked`

| ID | Owner | Claim (short) | Status | Config | Notes |
|----|-------|---------------|--------|--------|-------|
| `bias-1-vs-3-small` | Caden | Multi-model + consensus reduces bias/hallucination vs 1 small LLM | planned | `configs/bias-1-vs-3-small.yaml` | |
| `bias-3-small-vs-gemini` | Ethan | Crowd of small models competitive with / complementary to a strong single model | planned | `configs/bias-3-small-vs-gemini.yaml` | |
| `tiebreak-nonsense` | Caden | Tie-breaker rejects unsupported / nonsense candidates | planned | `configs/tiebreak-nonsense.yaml` | |
| `tiebreak-non-nonsense` | Caden | Tie-breaker resolves plausible disagreement toward supported answer | planned | `configs/tiebreak-non-nonsense.yaml` | |
| `cost-benefit-1-vs-3` | Caden | Quality gain vs compute cost of 1 vs 3 extractors (+ consensus) | planned | `configs/cost-benefit-1-vs-3.yaml` | May share runs with bias-1-vs-3 |
| `cost-benefit-3-vs-gemini` | Ethan | Cost/quality of 3-small vs Gemini; with/without supplied summaries | planned | `configs/cost-benefit-3-vs-gemini.yaml` | |
| `split-vs-not` | Caden | How often field decisions are unanimous vs split before tie-break | planned | `configs/split-vs-not.yaml` | Often derived from bias/cost runs |
| `go-term-distance` | Ethan | Quantify GO/category disagreement distance | planned | `configs/go-term-distance.yaml` | Coordinate with Braden |
| `completion-accuracy` | TBD | End-to-end completion and accuracy metrics | planned | `configs/completion-accuracy.yaml` | Later |
| `source-clarity-false-cognates` | TBD | False-cognate / organism conflation failure modes | planned | `configs/source-clarity-false-cognates.yaml` | |
| `ortholog-benefit` | TBD | Benefit of ortholog fallback when direct literature is thin | planned | `configs/ortholog-benefit.yaml` | |

### Suggested (not yet assigned)

Add rows here when proposed experiments are accepted into the paper plan.
See discussion notes outside this file for candidates (e.g. relevance diminishing returns).

| ID | Owner | Claim (short) | Status | Config | Notes |
|----|-------|---------------|--------|--------|-------|
| _(none yet)_ | | | | | |

## Condition naming

Use stable condition ids in JSONL, e.g.:

- `extractor_single_<model>`
- `extractors_k3_plus_consensus`
- `gemini_direct`
- `gemini_with_supplied_summaries`

## Revision log

| Date | Change |
|------|--------|
| 2026-08-21 | Initial layout and registry scaffold |
