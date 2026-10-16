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
  `decision_metrics` (`llm_duration_sec` / `classifier_duration_sec`; Arm D also stores
  `claim_scores`: one `{claim_index, field, source_model, source_value, text, score}` per claim,
  so threshold sweeps can be recomputed offline without rerunning the classifier)
- `errors.jsonl` — trials that failed (soft-fail); not in `records.jsonl`, so a re-run retries them

## Resume

Re-running the same arm with the same `--run-id` skips trial_ids already in that arm's
`records.jsonl`. If a classifier backend is skipped (e.g. insufficient VRAM for
`bespoke_minicheck_7b`) the arm stops with status `aborted` and exit code 2.

Use `--max-trials N` to cap the number of trials (first N biology trials).

---

## Phase 3 (fresh extraction + Phase 2 gold)

Phase 3 runs **new** extractor calls for the four models used by the arms, then
reuses the same sequential arm loop as Phase 1. Config:
`experiments/paper/configs/consensus-arms-phase3.yaml` (extraction +
`source_records` / arms keys in one file).

**Scope:** experiments branch only. Do not edit `worker/`, `deploy/`, production
`autoannotation/consensus.py`, or worker.env defaults.

### 1. Extraction

```bash
PYTHONPATH=. python -m experiments.paper.runners.run_bias_1_vs_3 \
  --config experiments/paper/configs/consensus-arms-phase3.yaml \
  --run-id consensus_arms_phase3
```

The Phase 2 labeled set is 120 sections in
`experiments/paper/fixtures/gold/consensus_arms_v1/` (`sample_manifest.json`,
`stubs.jsonl`, `dev_papers.json`, `test_papers.json`). Prefer extracting those
exact `trial_id`s when possible.

`run_bias_1_vs_3.py` has **no** `--trial-id` filter: it samples from
`fixtures/paper_snapshots/bias_cluster_v2.json` via `distribution` / `n_trials`
in the YAML (default 120 biology trials, 40 per organism, seed 42). That pool
overlaps the Phase 2 fixture but **does not guarantee** the same 120
`trial_id`s as `sample_manifest.json`. Practical options:

- Run extraction on the full configured pool, then run arms on all biology trials
  in `records.jsonl`; scoring via compare/spreadsheet only hits trials that have
  label packets (see step 4).
- After extraction, restrict attention to trials whose `trial_id` appears in
  `sample_manifest.json` (manual filter or ad-hoc script — not part of the
  runner CLI).

Records path (default run id):

`experiments/paper/results/bias-1-vs-3-small/consensus_arms_phase3/records.jsonl`

### 2. Point arms at the extraction run

Set `source_records` in `consensus-arms-phase3.yaml` to that run's
`records.jsonl` (or edit the path in the YAML before the arm loop if you used a
different `--run-id`).

### 3. Sequential arms (same list as Phase 1)

```bash
RUN=consensus_arms_phase3
for ARM in A B B-ref C D:minicheck_ft5 D:hhem D:bespoke_minicheck_7b; do
  PYTHONPATH=. python -m experiments.paper.runners.run_consensus_arms \
    --config experiments/paper/configs/consensus-arms-phase3.yaml \
    --arm "$ARM" --run-id "$RUN"
done
```

Arm behaviour, soft-fail/resume, and output layout match Phase 1 under
`experiments/paper/results/consensus-arms/<run_id>/arm_<safe_name>/`.

### 4. Spreadsheets and compare (Phase 2 labels)

> **Schema mismatch - read before scoring Phase 3.** `build_consensus_arms_spreadsheet.py` and
> `compare_consensus_arms.py` were built for **Phase 1 model-spread reviewer labels**: `t*.json`
> files with per-extractor `fields[f].labels[model]` (`correct` / `partial` / ...). Phase 2 gold
> (`stubs.jsonl`) instead has per-field `gold_status` / `gold_value` / `gold_quote` and **no
> `labels[model]`**. Exporting stubs to `t*.json` is therefore **not enough**: every arm value
> would be UNLABELED. Phase 3 scoring needs one of (a) a scorer that compares each arm's values
> to the gold needles (not implemented), or (b) the frontier judging step that produces
> per-extractor labels for the Phase 3 outputs. Until then the commands below are only valid
> with Phase 1-style `t*.json` labels.

Label packets live under `labels_dir` in the YAML
(`experiments/paper/fixtures/gold/consensus_arms_v1` for Phase 2 gold; Phase 1 labels are in
`experiments/paper/results/model_spread_15k/labels/`).

**Reading `scoreboard.csv`:** `fp` counts only *labeled* false positives. A non-null value that
matches no labeled candidate (B judge merges, D reassembled strings) is UNLABELED, so `fp` alone
undercounts when UNLABELED > 0. Use `unlabeled_non_needle` (unjudged values on no-needle fields)
and `fp_upper_bound` = `fp` + `unlabeled_non_needle` as the FP-risk bound; `unlabeled_on_needles`
/ `recall_upper_bound` is the matching recall bound. `vs_A.md` repeats this caveat and lists the
unjudged no-needle values new vs A.

```bash
LABELS=experiments/paper/results/model_spread_15k/labels   # t*.json with labels[model]; see note above
RUN=consensus_arms_phase3
for ARM in A B B-ref C D:minicheck_ft5 D:hhem D:bespoke_minicheck_7b; do
  PYTHONPATH=. python experiments/paper/scripts/build_consensus_arms_spreadsheet.py \
    --arm-dir experiments/paper/results/consensus-arms/$RUN/arm_${ARM//:/_} \
    --labels "$LABELS" \
    --out ~/Downloads/consensus_arms_${RUN}_arm_${ARM//:/_}_team_review.xlsx
done

PYTHONPATH=. python experiments/paper/scripts/compare_consensus_arms.py \
  --run-dir experiments/paper/results/consensus-arms/$RUN \
  --labels "$LABELS" \
  --out experiments/paper/results/consensus-arms/$RUN/compare/
```

### 5. Dev / test protocol (Arm D and paper result)

Use **`dev_papers.json`** only to tune Arm D: pick the classifier
(`D:minicheck_ft5`, `D:hhem`, or `D:bespoke_minicheck_7b`) and set
`d_threshold` in the YAML (pilot default `0.5`). Filter compare/spreadsheet
rows or ad-hoc analysis to trials whose `pmc_id` is in the dev list. **Freeze**
the chosen classifier and threshold before touching test.

Score **held-out test** using **`test_papers.json`** only (trials on those
`pmc_id`s). Success bar: beat arm A on test — **more needles found** and
**fewer false positives** than A, not merely matching A.

Phase 1 pilot metrics are go/no-go only; the paper claim comes from this
dev-tune / test-score split on Phase 2 gold.

### 6. Production boundary

Phase 3 does not change deployment, worker defaults, or production consensus
code. Arm B still calls production hybrid consensus via import only; extractors
run through the existing paper bias runner.
