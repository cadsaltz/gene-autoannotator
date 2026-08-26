import csv
import json

import pytest

from experiments.paper.runners import run_bias_1_vs_3


def test_dry_run_writes_general_manifest_and_aggregate(tmp_path, monkeypatch):
    fixture_path = tmp_path / 'fixture.json'
    fixture_path.write_text(json.dumps({
        'items': [{
            'trial_id': 'trial-1',
            'category': 'grounded',
            'profile_id': 'grounded',
            'source_id': 'squad:1',
            'gene_id': 'squad:1',
            'gene_name': 'grounded',
            'section': 'grounded',
            'excerpt_text': 'Paris is the capital of France.',
            'focus_question': 'What is the capital of France?',
        }],
    }))
    config_path = tmp_path / 'config.yaml'
    config_path.write_text(
        'experiment_id: bias-1-vs-3-small\n'
        'n_trials: 1\n'
        'fixtures:\n'
        f'  general: {fixture_path}\n'
        'models:\n'
        '  extractors: [model-a, model-b, model-c]\n'
        '  consensus: model-d\n',
    )
    paper_dir = tmp_path / 'paper'
    monkeypatch.setattr(run_bias_1_vs_3, 'PAPER_DIR', paper_dir)

    output_dir = run_bias_1_vs_3.run_bias_experiment(
        config_path=config_path,
        run_id='dry-test',
        dry_run=True,
    )

    manifest = json.loads((output_dir / 'manifest.json').read_text())
    assert manifest['experiment_id'] == 'bias-1-vs-3-small'
    assert manifest['extraction_fields_by_pool']['general'] == [
        'direct_answer',
        'supporting_fact',
        'extra_detail',
    ]

    with (output_dir / 'aggregate.csv').open(newline='') as handle:
        rows = list(csv.DictReader(handle))
    assert [row['condition'] for row in rows if row['scope'] == 'overall'] == list(run_bias_1_vs_3.CONDITIONS)
    assert all(int(row['field_scores']) == 0 for row in rows)
