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
