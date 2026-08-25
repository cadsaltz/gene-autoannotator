# Fixtures

Frozen inputs. Prefer small, pre-registered sets with explicit selection criteria.

| Path | Purpose |
|------|---------|
| `gene_sets/` | Gene/locus lists + selection rationale |
| `paper_snapshots/` | PMC ids and/or hashed paths to frozen excerpt text |
| `gold/` | Trusted / human labels for scoring (when used) |
| `constructed/` | Synthetic cases (nonsense candidates, planted splits, false cognates) |

Each fixture file should include:

- `fixture_id`
- `selection_criteria` (how items were chosen)
- `items` (the actual list)

Do not expand a fixture after analysis has started without versioning it.
