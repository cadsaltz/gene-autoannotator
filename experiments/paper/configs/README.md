# Configs

Frozen experiment configs (YAML). One file per experiment id in `PROTOCOL.md`.

Required keys (convention):

```yaml
experiment_id: example-id
owner: name
claim: One sentence claim this run is meant to support.
status: planned

models:
  # exact tags / ids; never vague names
  extractors: []
  consensus: null
  baselines: []

fixtures:
  genes: fixtures/gene_sets/PLACEHOLDER.json
  papers: fixtures/paper_snapshots/PLACEHOLDER.json
  gold: fixtures/gold/PLACEHOLDER.json  # optional

conditions: []   # stable condition ids

metrics: []      # names of aggregate columns to produce

notes: |
  Free-form protocol notes. Selection criteria, exclusions, shared-run links.
```

Do not edit a config after its first paper-facing run without bumping a
`config_version` and recording the change in `PROTOCOL.md`.
