import csv
import json

from experiments.paper.runners import run_bias_1_vs_3


def test_dry_run_writes_single_records_file_for_mixed_distribution(tmp_path, monkeypatch):
    biology_fixture = tmp_path / 'biology.json'
    biology_fixture.write_text(json.dumps({
        'items': [{
            'trial_id': 'bio-1',
            'profile_id': 'mtb-h37rv',
            'gene_id': 'Rv0001',
            'gene_name': 'dnaA',
            'section': 'abstract',
            'excerpt_text': 'Biology excerpt.',
        }],
    }))
    general_fixture = tmp_path / 'general.json'
    general_fixture.write_text(json.dumps({
        'items': [{
            'trial_id': 'gen-1',
            'category': 'truthful',
            'profile_id': 'truthful',
            'source_id': 'truthfulqa:1',
            'section': 'truthful',
            'excerpt_text': 'General excerpt.',
            'focus_question': 'Question?',
        }],
    }))
    config_path = tmp_path / 'config.yaml'
    config_path.write_text(
        'experiment_id: bias-1-vs-3-small\n'
        'fixtures:\n'
        f'  papers: {biology_fixture}\n'
        f'  general: {general_fixture}\n'
        'models:\n'
        '  extractors: [model-a, model-b, model-c]\n'
        '  consensus: model-d\n',
    )
    paper_dir = tmp_path / 'paper'
    monkeypatch.setattr(run_bias_1_vs_3, 'PAPER_DIR', paper_dir)

    output_dir = run_bias_1_vs_3.run_bias_experiment(
        config_path=config_path,
        run_id='mixed20',
        dry_run=True,
        distribution={'mtb-h37rv': 1, 'truthful': 1},
    )

    manifest = json.loads((output_dir / 'manifest.json').read_text())
    assert manifest['run_id'] == 'mixed20'
    assert manifest['n_trials'] == 2
    assert manifest['trial_pools'] == {'biology': 1, 'general': 1}

    records = [
        json.loads(line)
        for line in (output_dir / 'records.jsonl').read_text().splitlines()
        if line.strip()
    ]
    observables = [r for r in records if r['record_type'] == 'trial_observable']
    assert len(observables) == 2
    assert {row['trial_pool'] for row in observables} == {'biology', 'general'}

    with (output_dir / 'aggregate.csv').open(newline='') as handle:
        rows = list(csv.DictReader(handle))
    assert any(row['scope'] == 'biology' for row in rows)
    assert any(row['scope'] == 'general' for row in rows)
