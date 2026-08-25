# Results

Run outputs. Layout:

```text
results/<experiment_id>/<run_id>/
  manifest.json
  records.jsonl
  aggregate.csv
  aggregate.json    # optional
  notes.md          # optional human notes for this run
```

**Commit:** manifests, aggregates, and small derived tables needed for the paper.

**Usually gitignore:** huge raw LLM dumps, full text caches, per-token logs.
If raw dumps are needed for audit, store externally and record hashes in the manifest.

Paper tables should cite `experiment_id`, `run_id`, git SHA, and config version.
