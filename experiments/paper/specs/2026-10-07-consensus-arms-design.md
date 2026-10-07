# Consensus arms: can a multi-extractor crowd beat gemma4 alone?

Date: 2026-10-07
Status: approved design, pending implementation plan

## Goal

The paper's thesis is that a crowd of extractors yields more trustworthy annotations from the
literature than a single model. The model-spread experiment (run `mixed20_model_spread_15k`) found the
opposite under the current consensus: gemma4:12b alone found 15 of 18 needles with 0 false positives,
and no 3-extractor consensus beat it.

This experiment tests whether changing the step after extraction lets a 3-extractor crowd beat
gemma4:12b alone.

## Success bar

An arm beats arm A only if, on the test split, it finds **more** needles **and** produces **fewer**
false positives than A. A tie on either count is not a win.

## Definitions

- **Needle:** one (gene, section, field) whose value the excerpt explicitly supports for the target gene,
  under the strict rules of the extraction prompt.
- **Found:** the arm's value for that field is correct (clean) or correct with unsupported extras (padded).
- **Missed:** the arm returned null for a needle field.
- **False positive:** a non-null value the excerpt does not support for the target gene, split into
  hallucinated (not in the excerpt), wrong gene (in the excerpt but about another gene), and
  overreach (a supported-looking value on a field with no needle).

## Arms

All arms share one extraction run. Extractors run once with the unchanged extraction prompt on the full
chunk (no keyword windows, no gene-mention gating). Arms differ only in the decision step that turns
extractor outputs into the annotation.

| Arm | Extractors | Decision step |
|---|---|---|
| A | gemma4:12b | none; gemma's output is the annotation |
| B | gemma4:12b + phi4:14b + dolphin3:8b | current consensus: `ceil(n/2)` vote gate, then LLM batch merge **without** the excerpt; consensus model gemma4:26b |
| B-ref | gemma4:12b + phi4:14b + granite4.2:8b | same as B (reference row: B's best trio on existing data) |
| C | same trio as B | **no vote gate**; every candidate, the full excerpt and the target gene go to the consensus LLM, which keeps the candidates the excerpt supports for the target gene; judge gemma4:26b |
| D | same trio as B | **no vote gate**; a local classifier scores each candidate claim against the excerpt; keep candidates above a threshold |

Rationale:

- The B trio (gemma4 + phi4 + dolphin3) is chosen for recall: on existing data its union covers all 18
  needles, including the 3 gemma4 missed (found only by dolphin3).
- C and D must drop the vote gate; otherwise needles found by one extractor never reach the judge.
- B and C use the same judge model (gemma4:26b) so model size is not a factor; B vs C isolates the
  excerpt and the vote gate. Smaller or different judges are a later optimization.
- Today's consensus prompt (`BATCH_CONSENSUS_PROMPT`) contains only candidate JSON and field names.
  The excerpt is used only afterwards by a word-overlap validator.

### Arm D classifiers

Open-weight, run locally on sch (RTX 2070 Max-Q, 8 GB VRAM, no native BF16):

- MiniCheck-Flan-T5-Large (770M)
- HHEM-2.1-open (~600M)
- Bespoke-MiniCheck-7B, 4-bit quantized (license to be checked before any deployment use)
- Bespoke-Nimble-9B, 4-bit quantized, only if quantizing works without significant effort; otherwise
  recorded as skipped

Jev (TypeSafe) is excluded: closed weights, paid cloud API.

### Claims for arm D

Built deterministically from candidates, no LLM rewriting:

- `function`: split into sentences; each prefixed with organism, gene name and locus id.
- `functional_category`: one claim per tag, e.g. "Gene murG (b0090) is involved in peptidoglycan
  biosynthesis."
- drug, infection and essentiality fields: one claim each with the gene named explicitly.

Each claim is kept or dropped on its own: a `function` value keeps only its passing sentences, and a
`functional_category` value keeps only its passing tags. A field with no passing claims is null.
Context is the full chunk; classifiers with short input limits score the claim against overlapping
slices of the chunk and take the maximum.

### Arm C output

The judge returns, per field, the subset of candidate values it considers supported, selected verbatim
(no rewriting). Duplicate and paraphrased values are left for aggregation to merge.

## Phases

### Phase 1: pilot on existing data

Data: the 33 labeled biology parts and the 9 extractors' saved outputs from `mixed20_model_spread_15k`
(labels in `experiments/paper/results/model_spread_15k/labels/`).

Score A, B, B-ref, C, and D (one row per classifier) as post-processing over the saved extractor
outputs. B and C call gemma4:26b on sch; D calls the classifiers. No new extraction.

The 18 needles are too few to tune and test on the same data, so the pilot reports D at
leave-one-paper-out thresholds and is treated as a go/no-go signal, not as the result.

### Phase 2: larger labeled set (in parallel with phase 1)

- 120 sections from the frozen 300-section pool (`fixtures/paper_snapshots/bias_cluster_v2.json`),
  40 per organism, spread across papers.
- Dev/test split 50/50 by paper; no paper appears on both sides.
- Needles found blind by frontier-model subagents per section (field, value, verbatim quote) before any
  model output is seen. A random 15% of sections is labeled by a second subagent; disagreements go to
  the user.

### Phase 3: final comparison

- One extraction run of gemma4:12b, phi4:14b, dolphin3:8b (and granite4.2:8b for B-ref) over the
  120 sections.
- On dev: choose D's classifier and threshold.
- On test: report every arm.

## Scoring and reporting

- Frontier-model subagents judge each arm's non-null values against the needle labels and the
  excerpt (found clean, found padded, hallucinated, wrong gene, overreach); misses are computed from
  the labels.
- Per arm: the scoreboard used in the model-spread review (needle fields: found clean / found padded /
  answered wrong / missed; no-needle fields: correctly empty / filled anyway).
- Per arm vs A: needle-by-needle lists of what the arm found that A missed, what it lost that A found,
  and each false positive added or removed; a confidence interval from resampling papers.
- Cost: shared extraction time, plus decision-step seconds per section for each arm.
- Spreadsheet: the same review overlay (needles highlighted in excerpts, flags per output), with one
  output row per arm.

## Runner changes

- `single_*` conditions reuse `extractor_*` outputs instead of repeating the calls.
- Decision steps (B, C, D) run as post-processing over saved extractor outputs, so new judges or
  classifiers can be added without re-extracting.
- Production consensus code is not changed by this experiment.

## Out of scope

- Prompt changes, keyword windows or gene-mention gating for extraction.
- Per-model tuning (thinking modes, chunk sizes, per-model prompts) and new extractor models.
- Choosing a smaller or cheaper judge for production.
- Alias harvesting across chunks (a possible later fix for abbreviations defined in an earlier chunk).
