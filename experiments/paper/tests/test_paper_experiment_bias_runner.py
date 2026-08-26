import csv
import json

import pytest

from experiments.paper.runners import run_bias_1_vs_3


def test_aggregate_rates_exclude_nulls_except_null_rate():
    scores = [
        {'condition': 'extractor_A', 'trial_pool': 'biology', 'groundedness_label': 'supported'},
        {'condition': 'extractor_A', 'trial_pool': 'biology', 'groundedness_label': 'unsupported'},
        {'condition': 'extractor_A', 'trial_pool': 'biology', 'groundedness_label': 'null'},
        {'condition': 'extractor_A', 'trial_pool': 'biology', 'groundedness_label': 'null'},
    ]

    rows = run_bias_1_vs_3._aggregate_rows(scores, [], conditions=('extractor_A',))
    row = next(row for row in rows if row['condition'] == 'extractor_A' and row['scope'] == 'overall')

    assert row['supported_rate'] == pytest.approx(0.5)
    assert row['unsupported_rate'] == pytest.approx(0.5)
    assert row['null_rate'] == pytest.approx(0.5)


def test_dry_run_writes_placeholder_aggregate(tmp_path, monkeypatch):
    fixture_path = tmp_path / 'fixture.json'
    fixture_path.write_text(json.dumps({
        'items': [{
            'trial_id': 'trial-1',
            'profile_id': 'mtb-h37rv',
            'gene_id': 'Rv0001',
            'gene_name': 'dnaA',
            'pmc_id': 'PMC1',
            'section': 'abstract',
            'excerpt_text': 'Frozen excerpt.',
        }],
    }))
    config_path = tmp_path / 'config.yaml'
    config_path.write_text(
        'experiment_id: bias-1-vs-3-small\n'
        'n_trials: 1\n'
        'fixtures:\n'
        f'  papers: {fixture_path}\n'
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

    with (output_dir / 'aggregate.csv').open(newline='') as handle:
        rows = list(csv.DictReader(handle))
    overall_rows = [row for row in rows if row['scope'] == 'overall']
    assert [row['condition'] for row in overall_rows] == list(run_bias_1_vs_3.CONDITIONS)
    assert all(int(row['field_scores']) == 0 for row in overall_rows)
    assert all(float(row['unsupported_rate']) == 0.0 for row in rows)
