# Paper experiment runners

Shared helpers in `common.py`:

- `load_yaml_config`, `load_paper_snapshot_fixture`, `select_trials`
- `stable_json_hash`, `new_run_id`
- `write_json`, `append_jsonl`, `write_aggregate_csv`
- `BIOLOGY_FIELDS`, `is_nullish`, `field_values_equal`

## Entrypoints (bias / split / cost cluster)

Run from repo root with `PYTHONPATH=.` and `.venv` activated.

| Module | Role | Example |
|--------|------|---------|
| `run_bias_1_vs_3` | Primary LLM + NLI run | `python -m experiments.paper.runners.run_bias_1_vs_3 --config experiments/paper/configs/bias-1-vs-3-small.yaml --n-trials 10 --run-id paper10` |
| `derive_split_vs_not` | Split classification derive | `python -m experiments.paper.runners.derive_split_vs_not --bias-run-dir experiments/paper/results/bias-1-vs-3-small/paper10 --run-id split_from_paper10` |
| `derive_cost_benefit_1_vs_3` | Joint quality×cost derive | `python -m experiments.paper.runners.derive_cost_benefit_1_vs_3 --bias-run-dir experiments/paper/results/bias-1-vs-3-small/paper10 --run-id cost_from_paper10` |

Supporting modules (imported, not CLI): `groundedness.py` (NLI), `split_classify.py` (unanimous/split/partial).

Pilot and paper-10 operator sequence: `experiments/paper/analysis/bias_split_cost.md`.
