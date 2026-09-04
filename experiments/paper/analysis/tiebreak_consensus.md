# Tie-break consensus operator notes

The two experiments use the same frozen constructed fixture and runner. They
never provide a source excerpt to consensus; live runs therefore test
candidate-only reconciliation, not source-grounded biological accuracy.

## Dry-run smoke checks

```bash
python -m experiments.paper.runners.run_tiebreak_consensus \
  --config experiments/paper/configs/tiebreak-non-nonsense.yaml \
  --dry-run --limit 3

python -m experiments.paper.runners.run_tiebreak_consensus \
  --config experiments/paper/configs/tiebreak-nonsense.yaml \
  --dry-run --limit 3
```

## Live runs

Ensure Ollama has the pinned `qwen3:0.6b` model, then run:

```bash
python -m experiments.paper.runners.run_tiebreak_consensus \
  --config experiments/paper/configs/tiebreak-non-nonsense.yaml \
  --run-id paper-non-nonsense-v1

python -m experiments.paper.runners.run_tiebreak_consensus \
  --config experiments/paper/configs/tiebreak-nonsense.yaml \
  --run-id paper-nonsense-v1
```

Each command writes `manifest.json`, `records.jsonl`, and `aggregate.csv` under
`experiments/paper/results/<experiment-id>/<run-id>/`.

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
- `nonsense_majority_adoption_rate` for `tiebreak-nonsense`

The `domain`, `case_family`, and `expect_llm` rows support stratified appendix
checks. Exact-match rates are secondary diagnostics; soft-match rates are the
pre-registered primary outcome.
