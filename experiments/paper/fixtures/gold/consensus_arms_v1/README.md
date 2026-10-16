# consensus_arms_v1: Phase 2 labeled set

120 sections (40 each: `ecoli-k12-mg1655`, `mtb-h37rv`, `tcruzi-clbrener`) sampled from
`../../paper_snapshots/bias_cluster_v2.json`. Gold fields are **empty** until labeled.

Regenerate (deterministic for a given seed and fixture; overwrites these files, including any labels in `stubs.jsonl`):

```bash
PYTHONPATH=. python experiments/paper/scripts/sample_consensus_arms_sections.py --seed 42 --per-organism 40
```

## Files

| File | Contents |
|------|----------|
| `stubs.jsonl` | One gold stub per line (**single-file format**, chosen over per-trial JSON files) |
| `sample_manifest.json` | Seed, counts, source fixture, ordered `trial_ids` |
| `dev_papers.json` / `test_papers.json` | Disjoint `pmc_id` lists (50/50, stratified by organism). A paper's sections are all dev or all test |
| `double_label_ids.json` | Random 15% of `trial_ids` (18) for a second blind labeling pass |

Sections are spread across papers: within an organism every paper is used once before any is reused
(E. coli and T. cruzi have only ~20 papers each, so some papers contribute 2+ sections).

Stub shape:

```json
{"trial_id": "...", "gene_id": "...", "gene_name": "...", "profile_id": "...", "pmc_id": "...",
 "section": "...", "excerpt_text": "...", "fields": {}, "needs_human": false}
```

## Filling fields (blind)

1. Label with `../../constructed/CONSENSUS_ARMS_NEEDLE_PROMPT.md`, one stub per subagent/labeler.
   Rubric: `results/model_spread_15k/labels/RUBRIC.md` (excerpt-only, target gene only, null when unsupported).
2. **Blind** means the labeler sees only the stub (`excerpt_text` plus gene identity). Never show extractor/model
   outputs, arm results, other labelers' answers, or `results/`.
3. Fill `fields` with one entry per biology field (4 for `mtb-h37rv`; 6 otherwise):
   `{"gold_status": "present|absent", "gold_value": ..., "gold_quote": "verbatim <=200 chars or null"}`.
   Keep `needs_human: false` after a first pass.
4. Write results back into `stubs.jsonl` (same line order and keys; only `fields` changes).

## Double labeling and disagreements

1. For each `trial_id` in `double_label_ids.json`, run a second independent blind pass (fresh labeler, no sight of the first).
   Store the second pass separately (e.g. `second_pass.jsonl`); do not overwrite first-pass `fields`.
2. Compare per field: disagreement if `gold_status` differs, or both are `present` and `gold_value` is not equivalent
   (booleans must match exactly; for text/tag lists, a different supported claim or tag set).
3. On any disagreement set `needs_human: true` on that stub. A human reviewer resolves it, writes the final `fields`,
   and sets `needs_human` back to `false` (note the resolution in the commit or PR).
4. Report agreement rate over the double-labeled subset (per field and overall).
