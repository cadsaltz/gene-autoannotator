# Fixtures

Frozen inputs. Prefer small, pre-registered sets with explicit selection criteria.

| Path | Purpose |
|------|---------|
| `gene_sets/` | Gene/locus lists + selection rationale |
| `paper_snapshots/` | PMC ids and/or hashed paths to frozen excerpt text |
| `paper_snapshots/bias_cluster_v1.json` | Original 15-trial MTB-only pool |
| `paper_snapshots/bias_cluster_v2.json` | 300-trial multi-organism pool (100 MTB + 100 E. coli + 100 T. cruzi) |
| `gold/` | Trusted / human labels for scoring (when used) |
| `constructed/` | Synthetic cases (nonsense candidates, planted splits, false cognates) |

Build `bias_cluster_v2` with:

```bash
python experiments/paper/scripts/build_multi_organism_fixture.py --expand-cache
```

Run a mixed distribution (example 5+5+5):

```bash
python experiments/paper/runners/run_bias_1_vs_3.py \
  --config experiments/paper/configs/bias-multi-organism-v2.yaml \
  --distribution mtb-h37rv:5 \
  --distribution ecoli-k12-mg1655:5 \
  --distribution tcruzi-clbrener:5 \
  --run-id mixed15
```

Each fixture file should include:

- `fixture_id`
- `selection_criteria` (how items were chosen)
- `items` (the actual list)

Do not expand a fixture after analysis has started without versioning it.
