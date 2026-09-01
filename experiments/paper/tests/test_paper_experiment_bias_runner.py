import csv
import json

import pytest

from experiments.paper.runners import run_bias_1_vs_3


def test_aggregate_rows_report_timing_and_trial_counts():
    observables = [
        {
            'trial_pool': 'biology',
            'condition_metrics': {
                'extractor_A': {
                    'duration_sec': 2.0,
                    'llm_duration_sec': 1.0,
                    'model': 'model-a',
                    'usage': {'calls': 1, 'known_total_tokens': 100},
                },
            },
        },
        {
            'trial_pool': 'biology',
            'condition_metrics': {
                'extractor_A': {
                    'duration_sec': 4.0,
                    'llm_duration_sec': 3.0,
                    'model': 'model-a',
                    'usage': {'calls': 1, 'known_total_tokens': 200},
                },
            },
        },
    ]

    rows = run_bias_1_vs_3._aggregate_rows(
        observables,
        conditions=('extractor_A',),
    )
    row = next(row for row in rows if row['condition'] == 'extractor_A' and row['scope'] == 'overall')

    assert row['n_trials'] == 2
    assert row['mean_wall_time_sec'] == pytest.approx(3.0)
    assert row['mean_llm_time_sec'] == pytest.approx(2.0)
    assert row['mean_known_total_tokens'] == pytest.approx(150.0)


def test_dry_run_expands_chunked_trials(tmp_path, monkeypatch):
    max_chars = 500
    full_text = ('A' * max_chars + '\n\n') * 8
    monkeypatch.setenv('AUTOANNOTATION_SECTION_EXCERPT_MAX_CHARS', str(max_chars))
    monkeypatch.setenv('AUTOANNOTATION_SECTION_RETRIEVAL_THRESHOLD_CHARS', '50000')

    fixture_path = tmp_path / 'fixture.json'
    fixture_path.write_text(json.dumps({
        'items': [{
            'trial_id': 'trial-1',
            'trial_pool': 'biology',
            'profile_id': 'mtb-h37rv',
            'gene_id': 'Rv0001',
            'gene_name': 'dnaA',
            'pmc_id': 'PMC1',
            'section': 'results',
            'excerpt_text': full_text,
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

    manifest = json.loads((output_dir / 'manifest.json').read_text())
    assert manifest['n_fixture_trials'] == 1
    assert manifest['n_run_trials'] >= 2

    with (output_dir / 'aggregate.csv').open(newline='') as handle:
        rows = list(csv.DictReader(handle))
    overall_rows = [row for row in rows if row['scope'] == 'overall']
    assert [row['condition'] for row in overall_rows] == list(run_bias_1_vs_3.CONDITIONS)
    assert all(int(row['n_trials']) >= 2 for row in overall_rows)
