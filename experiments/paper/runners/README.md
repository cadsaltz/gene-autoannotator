# Runners

Thin scripts that execute a config and write the artifact contract under `results/`.

Conventions:

- Call existing `autoannotation` / `compareannotations` / consensus APIs; do not fork a second pipeline.
- Accept `--config path/to.yaml` and optional `--run-id`.
- Write `manifest.json`, `records.jsonl`, and `aggregate.csv` (or `.json`).
- Fail loudly if model tags in the config are missing or fixtures are absent.

Placeholders only for now; implement per experiment when fixtures and metrics are agreed.
