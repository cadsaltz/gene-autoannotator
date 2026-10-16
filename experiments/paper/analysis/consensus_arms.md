# Consensus arms pilot (Phase 1)

Compares consensus strategies over the biology trials of
`model_spread_15k` (outputs of the extractor models are reused; only the
decision step differs per arm).

| Arm | Candidates | Decision |
|---|---|---|
| `A` | gemma4:12b | passthrough |
| `B` | gemma4:12b, phi4:14b, dolphin3:8b | production hybrid consensus (judge `gemma4:26b`) |
| `B-ref` | gemma4:12b, phi4:14b, granite4.2:8b | same as B, alternate trio |
| `C` | trio B | excerpt-aware verbatim judge, no vote gate |
| `D:<clf>` | trio B | claims scored by classifier, kept if score >= `d_threshold` |

Classifiers: `minicheck_ft5`, `hhem`, `bespoke_minicheck_7b`.

## Run (sequential, one arm per process)

Arms run **one after another** so Ollama / the GPU is never shared across arms.

```bash
# Phase 1 — run arms one after another on sch
for ARM in A B B-ref C D:minicheck_ft5 D:hhem D:bespoke_minicheck_7b; do
  PYTHONPATH=. python -m experiments.paper.runners.run_consensus_arms \
    --config experiments/paper/configs/consensus-arms-pilot.yaml \
    --arm "$ARM" --run-id pilot_model_spread_15k
done
```

Smoke test without Ollama/classifiers (stub decisions for B/B-ref/C/D):

```bash
PYTHONPATH=. python -m experiments.paper.runners.run_consensus_arms \
  --config experiments/paper/configs/consensus-arms-pilot.yaml \
  --arm D:hhem --run-id smoke --dry-run --max-trials 5
```

## Live smoke (one trial, before the full pilot)

Run B and C on **one** trial each against the real Ollama host before launching the pilot.
Without `--dry-run` the runner calls `load_worker_env_into_process()` at start (same as
`run_bias_1_vs_3.py`; `worker.env` values only fill variables not already set), so only the
Ollama host and model tags matter here — chunking env is irrelevant for this post-process.

```bash
# Arm C: excerpt-aware verbatim judge (gemma4:26b)
PYTHONPATH=. python -m experiments.paper.runners.run_consensus_arms \
  --config experiments/paper/configs/consensus-arms-pilot.yaml \
  --arm C --run-id smoke_c --max-trials 1

# Arm B: production hybrid consensus, LlmHandler batch merge (gemma4:26b)
PYTHONPATH=. python -m experiments.paper.runners.run_consensus_arms \
  --config experiments/paper/configs/consensus-arms-pilot.yaml \
  --arm B --run-id smoke_b --max-trials 1
```

Requirements: the Ollama host from `worker.env` must be reachable and have the judge model
`gemma4:26b` pulled (`ollama pull gemma4:26b`). The candidate trio outputs are reused from
`source_records`, so extractor models are not called. Expect `arm=C status=complete trials=1
new=1 errors=0` and exit code 0; inspect `arm_<ARM>/records.jsonl` and
`decision_metrics.llm_duration_sec`. Use a fresh `--run-id` for the real pilot (smoke run-ids
are separate directories, and a live run can't resume a `--dry-run` manifest).

CI/unit tests never call Ollama; they mock `LlmHandler` and organism resolution.

## Soft-fail behaviour

Judge errors (Ollama down, model missing, malformed output) are caught **per trial**: the
trial is appended to `errors.jsonl` (`trial_id`, `error` as `ExceptionType: message`,
`traceback`), nothing is written to `records.jsonl` for it, and the arm continues with the
next trial. At the end the manifest status is `complete_with_errors` (`n_errors > 0`) and the
process exits 1. Re-running with the same `--run-id` retries only the failed trials. Only
classifier backend skips (`ClassifierSkipped`, arm D) abort the whole arm (status `aborted`,
exit 2). A failed trial is therefore *absent* from the arm's records rather than recorded as
an all-null output.

## Outputs

`experiments/paper/results/consensus-arms/<run_id>/arm_<safe_name>/` (`:` becomes `_`,
e.g. `arm_D_hhem`):

- `manifest.json` — arm, models, judge/classifier, git sha, source records, duration, status
- `records.jsonl` — per trial: `trial_id`, `excerpt_text`, `candidates`, `arm_output`,
  `decision_metrics` (`llm_duration_sec` / `classifier_duration_sec`)
- `errors.jsonl` — trials that failed (soft-fail); not in `records.jsonl`, so a re-run retries them

## Resume

Re-running the same arm with the same `--run-id` skips trial_ids already in that arm's
`records.jsonl`. If a classifier backend is skipped (e.g. insufficient VRAM for
`bespoke_minicheck_7b`) the arm stops with status `aborted` and exit code 2.

Use `--max-trials N` to cap the number of trials (first N biology trials).
