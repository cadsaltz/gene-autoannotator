"""Placeholder runner template.

Implement per experiment: load YAML config, run conditions, write
results/<experiment_id>/<run_id>/{manifest.json, records.jsonl, aggregate.csv}.
"""

from __future__ import annotations


def main() -> None:
    raise NotImplementedError(
        'Paper experiment runners are placeholders until fixtures and metrics are agreed.'
    )


if __name__ == '__main__':
    main()
