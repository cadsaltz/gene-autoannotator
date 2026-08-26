# Paper experiment fixtures

Frozen inputs for bias / cost-benefit paper experiments.

| Path | Purpose |
|------|---------|
| `gene_sets/` | Gene/locus lists + selection rationale |
| `paper_snapshots/` | PMC ids and/or hashed paths to frozen excerpt text |
| `paper_snapshots/bias_cluster_v1.json` | Original 15-trial MTB-only pool |
| `paper_snapshots/bias_cluster_v2.json` | 300-trial multi-organism pool (100 MTB + 100 E. coli + 100 T. cruzi) |
| `general_snapshots/general_cluster_v1.json` | 75-trial general extraction pool (25 truthful + 25 grounded + 25 trap) |
| `gold/` | Trusted / human labels for scoring (when used) |
| `constructed/` | Synthetic cases (nonsense candidates, planted splits, false cognates) |

Build `bias_cluster_v2` with:

```bash
python experiments/paper/scripts/build_multi_organism_fixture.py
```

Run a mixed distribution (example 5+5+5):

```bash
python experiments/paper/runners/run_bias_1_vs_3.py \
  --config experiments/paper/configs/bias-multi-organism-v2.yaml \
  --distribution mtb-h37rv:5 \
  --distribution ecoli-k12-mg1655:5 \
  --distribution tcruzi-clbrener:5 \
  --run-id mixed15 \
  --dry-run
```

Profile aliases: `mtb`, `ecoli`, `tcruzi`.

Build `general_cluster_v1` with:

```bash
python experiments/paper/scripts/build_general_cluster_v1.py
```

Run the general experiment (example 5+5+5):

```bash
python -m experiments.paper.runners.run_bias_general_1_vs_3 \
  --config experiments/paper/configs/bias-general-1-vs-3.yaml \
  --distribution truthful:5 \
  --distribution grounded:5 \
  --distribution trap:5 \
  --run-id general15 \
  --dry-run
```

Category names for `--distribution`: `truthful`, `grounded`, `trap`.
