# Analysis

Scripts/notebooks that turn `results/**/aggregate.*` into paper tables and figures.

Rules:

- Prefer reading aggregates (and, if needed, JSONL) — not live API calls.
- One analysis module (or notebook) per figure/table family when practical.
- Record which `run_id`s feed each figure in a short header comment or cell.

Placeholders only until first aggregates exist.
