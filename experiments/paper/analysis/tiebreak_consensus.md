# Tie-break consensus operator notes

Constructed tie-break experiments share one frozen fixture
(`fixtures/constructed/tiebreak_consensus_v1.json`) and one runner. Consensus
never receives a source excerpt; live runs test candidate-only reconciliation,
not source-grounded biological accuracy.

## Unified suite and presets

| Config | `experiment_id` | Cases selected |
|--------|-----------------|----------------|
| `tiebreak-consensus.yaml` | `tiebreak-consensus` | **Both** `tiebreak-non-nonsense` and `tiebreak-nonsense` (OR / any-of) |
| `tiebreak-non-nonsense.yaml` | `tiebreak-non-nonsense` | Non-nonsense tag only (legacy-compatible preset) |
| `tiebreak-nonsense.yaml` | `tiebreak-nonsense` | Nonsense tag only (legacy-compatible preset) |

The primary config runs the full paper suite in **one** `run_id` → one
`records.jsonl` → one `aggregate.csv` with overall rows plus
`scope=experiment_tag` slices. Nonsense-only metrics (e.g.
`nonsense_majority_adoption_rate`) are computed on the nonsense-tagged subset,
not diluted by non-nonsense rows.

## Flags

| Flag | Effect |
|------|--------|
| `--spreadsheet` | After a successful run, write `team_review.xlsx` in the run directory (Summary + per-tag case sheets). Lazy-imports `openpyxl`; not required for normal runs. |
| `--spreadsheet-strict` | Spreadsheet export errors fail the run (default: log warning and continue). |

Post-hoc export from an existing run directory:

```bash
python experiments/paper/scripts/build_tiebreak_team_review_spreadsheet.py \
  --run-dir experiments/paper/results/tiebreak-consensus/<run-id>
```

## Dry-run smoke checks

No LLM calls; writes manifest, records, aggregate, and (with `--spreadsheet`)
`team_review.xlsx`.

```bash
cd /path/to/gene-autoannotator
source .venv/bin/activate
export PYTHONPATH=.

# Combined suite (recommended)
python -m experiments.paper.runners.run_tiebreak_consensus \
  --config experiments/paper/configs/tiebreak-consensus.yaml \
  --dry-run --limit 3 --spreadsheet

# Preset subsets (legacy-compatible)
python -m experiments.paper.runners.run_tiebreak_consensus \
  --config experiments/paper/configs/tiebreak-non-nonsense.yaml \
  --dry-run --limit 3

python -m experiments.paper.runners.run_tiebreak_consensus \
  --config experiments/paper/configs/tiebreak-nonsense.yaml \
  --dry-run --limit 3
```

## Live runs

Use consensus model `qwen3.5:27b` (pinned in the tie-break configs). Ollama
chat calls disable thinking by default (`think=false`) so Qwen3 fills
`message.content` for structured JSON. Ensure Ollama has that model, then run:

```bash
# Combined tie-break (nonsense + non-nonsense) + review sheet
python -m experiments.paper.runners.run_tiebreak_consensus \
  --config experiments/paper/configs/tiebreak-consensus.yaml \
  --run-id paper-tiebreak-v5 \
  --spreadsheet

# Preset: nonsense only (legacy-compatible)
python -m experiments.paper.runners.run_tiebreak_consensus \
  --config experiments/paper/configs/tiebreak-nonsense.yaml \
  --run-id paper-nonsense-v5 \
  --spreadsheet

# Preset: non-nonsense only
python -m experiments.paper.runners.run_tiebreak_consensus \
  --config experiments/paper/configs/tiebreak-non-nonsense.yaml \
  --run-id paper-non-nonsense-v5 \
  --spreadsheet
```

Each command writes `manifest.json`, `records.jsonl`, and `aggregate.csv` under
`experiments/paper/results/<experiment-id>/<run-id>/`. With `--spreadsheet`,
`team_review.xlsx` is written in the same directory.

## 2026-09-03 live pilot and blocked full runs

The pinned `qwen3:0.6b` model was pulled successfully. The live non-nonsense
pilot used run id `pilot-limit3-20260903` and covered the first two exact cases
plus `general-apples-paraphrase-001`.

Pilot headline values (`scope=overall,value=all`, n=3):

- consensus soft match: `0.6667`; extractor-0 baseline soft match: `0.3333`
- necessity delta: `0.5000` across two necessity cases
- LLM invoked rate: `0.3333`; expected-LLM calibration: `1.0000`
- invention rate: `0.0000`

Routing was calibrated in this pilot: exact cases used deterministic `2/3_exact`
consensus and the apples paraphrase case used `llm_batch_merge`. Model quality
was not calibrated to the desired answer, however: for candidates
`apples are green and sour`, `red and delicious apples`, and
`apples are delicious and red`, the LLM returned the extractor-0 minority
`apples are green and sour`. Thus apples had `llm_invoked=true` but
`match_soft=false`; this is a substantive pinned-model failure, not a routing
failure.

Full live runs were started with run ids `paper-non-nonsense-v1` (20 cases) and
`paper-nonsense-v1` (12 cases), but neither completed. Ollama 0.33.1 became
wedged with `qwen3:0.6b` shown as `Stopping...`: `/api/version` remained
responsive while a minimal `/api/generate` probe timed out after 20 seconds.
The non-nonsense artifact stopped at 14 of 40 expected condition rows and the
nonsense artifact at 4 of 24; neither has an aggregate table and neither is
valid for paper reporting. Preserve them only as blocker diagnostics, then
rerun both ids after restarting or repairing Ollama.

## 2026-09-03 full-run retry

After Ollama again completed a minimal generation with the pinned
`qwen3:0.6b` model, the invalid `paper-*-v1` partial directories were deleted.
A fresh non-nonsense run, `full-non-nonsense-v1`, then stalled on its first
LLM-backed case: it remained at 4 of 40 condition rows for more than eight
minutes before `ollama ps` reported the model as `Stopping...`. The client was
terminated and the sequential `full-nonsense-v1` run was not started. No fresh
aggregate exists; the pilot values above remain the only valid aggregate
headlines, including the apples minority-selection failure.

## Paper table inputs

Use the `scope=overall,value=all` aggregate row for the headline table:

- `case_count`
- `consensus_match_soft_rate` and `baseline_match_soft_rate`
- `necessity_case_count` and `necessity_delta`
- `llm_invoked_rate` and `expect_llm_calibration_rate`
- `invention_rate`
- `nonsense_majority_adoption_rate` for nonsense-tagged rows (or
  `scope=experiment_tag,value=tiebreak-nonsense` on a combined run)

The `domain`, `case_family`, `expect_llm`, and `experiment_tag` rows support
stratified appendix checks. Exact-match rates are secondary diagnostics;
soft-match rates are the pre-registered primary outcome.
