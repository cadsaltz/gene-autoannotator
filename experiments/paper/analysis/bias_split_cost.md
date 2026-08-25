# Analysis: bias / split / cost cluster

Operator notes for the shared `bias_cluster_v1` fixture pool (15 sections, 12 genes).
All three experiments share one primary bias run; split and cost are derives only.

**Status:** Runners and derives are runnable. Live Ollama + NLI pilot has not been run in-repo;
paper-facing aggregates remain unanalyzed until `paper10` completes.

## Prerequisites

From repo root, with `.venv` activated and Ollama **performance** models pulled
per `experiments/paper/configs/bias-1-vs-3-small.yaml`
(`qwen3:14b`, `gemma3:12b`, `mistral-nemo:12b`, `qwen3:8b`):

```bash
cd /path/to/gene-autoannotator
source .venv/bin/activate
export PYTHONPATH=.
```

Dry-run wiring check (no LLM/NLI):

```bash
python -m experiments.paper.runners.run_bias_1_vs_3 \
  --config experiments/paper/configs/bias-1-vs-3-small.yaml \
  --n-trials 1 --run-id dry1 --dry-run
```

## Pilot (N=1)

Debug observability, timing, and cache policy before the paper run.

```bash
python -m experiments.paper.runners.run_bias_1_vs_3 \
  --config experiments/paper/configs/bias-1-vs-3-small.yaml \
  --n-trials 1 --run-id pilot1
```

After pilot, derive split and cost from the same bias run:

```bash
python -m experiments.paper.runners.derive_split_vs_not \
  --bias-run-dir experiments/paper/results/bias-1-vs-3-small/pilot1 \
  --run-id split_from_pilot1

python -m experiments.paper.runners.derive_cost_benefit_1_vs_3 \
  --bias-run-dir experiments/paper/results/bias-1-vs-3-small/pilot1 \
  --run-id cost_from_pilot1
```

**Pilot gate:** Inspect `trials/<trial_id>.json` for full excerpt + A/B/C/D + single JSON;
confirm `field_score` rows in `records.jsonl` and non-zero `field_scores` in `aggregate.csv`
before paper10 (live runs only — dry-run aggregate rows are zero-valued placeholders).

## Paper run (N=10)

Only after pilot looks good:

```bash
python -m experiments.paper.runners.run_bias_1_vs_3 \
  --config experiments/paper/configs/bias-1-vs-3-small.yaml \
  --n-trials 10 --run-id paper10

python -m experiments.paper.runners.derive_split_vs_not \
  --bias-run-dir experiments/paper/results/bias-1-vs-3-small/paper10 \
  --run-id split_from_paper10

python -m experiments.paper.runners.derive_cost_benefit_1_vs_3 \
  --bias-run-dir experiments/paper/results/bias-1-vs-3-small/paper10 \
  --run-id cost_from_paper10
```

Use `--primary-only` on the cost derive if the paper table omits per-extractor rows.

## Aggregate → paper mapping

Analysis reads frozen `aggregate.csv` files only (plus optional `records.jsonl` for
example trials and error-coincidence). Do not re-run models for table numbers.

| Paper claim / section | Source run | Aggregate file | Key columns / rows |
|-----------------------|------------|----------------|--------------------|
| **Bias:** crowd reduces unsupported vs singles | `bias-1-vs-3-small/paper10` | `aggregate.csv` | `condition`, `unsupported_rate`, `supported_rate`, `null_rate`; compare `consensus_D` vs `single_A/B/C` and `extractor_A/B/C` |
| **Bias:** error coincidence (appendix) | same bias run | `records.jsonl` (`field_score`) | Compute P(j unsupported \| i unsupported) across extractor pairs — not pre-aggregated |
| **Split:** disagreement motivates consensus | `split-vs-not/split_from_paper10` | `aggregate.csv` | `scope=overall`: `split_rate`, `unanimous_rate`, `partial_rate`; `scope=field` rows for per-field breakdown |
| **Cost/benefit:** quality × compute joint table | `cost-benefit-1-vs-3/cost_from_paper10` | `aggregate.csv` | Compare the `crowd` row (consensus quality; combined A+B+C+D cost) with `single_A/B/C`; `consensus_D` is detail only |

### Interpretation helpers (compute in analysis, not runners)

- `delta_unsupported(single_X − crowd)` — positive ⇒ crowd less unsupported.
- Cost derive manifest `crowd_timing_check` — sanity that crowd wall time exceeds singles under cold-cache policy.
- Filter dry-run artifacts: require `field_score` rows in bias `records.jsonl` and non-zero
  `field_scores` in bias `aggregate.csv` (manifest has no score count).

## Post-paper10 registry

After `paper10` aggregates are reviewed, update `PROTOCOL.md`:

- `bias-1-vs-3-small`, `split-vs-not`, `cost-benefit-1-vs-3` → `analyzed`
- Link frozen run ids (`paper10`, `split_from_paper10`, `cost_from_paper10`) in PROTOCOL notes
