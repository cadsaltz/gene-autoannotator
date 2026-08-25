import json

import pytest

from experiments.paper.runners import derive_split_vs_not


def _write_bias_run(tmp_path, *, observables):
    bias_dir = tmp_path / 'bias-run'
    bias_dir.mkdir()
    (bias_dir / 'manifest.json').write_text(json.dumps({
        'experiment_id': 'bias-1-vs-3-small',
        'run_id': 'synthetic-bias',
        'n_trials': len(observables),
    }))
    records = []
    for observable in observables:
        records.append({'record_type': 'trial_meta', 'trial_id': observable['trial_id']})
        records.append(observable)
    (bias_dir / 'records.jsonl').write_text(
        '\n'.join(json.dumps(record) for record in records) + '\n',
    )
    return bias_dir


def test_derive_split_rates_from_synthetic_bias_run(tmp_path, monkeypatch):
    paper_dir = tmp_path / 'paper'
    config_path = paper_dir / 'configs' / 'split-vs-not.yaml'
    config_path.parent.mkdir(parents=True)
    config_path.write_text('experiment_id: split-vs-not\n')
    monkeypatch.setattr(derive_split_vs_not, 'PAPER_DIR', paper_dir)

    observable = {
        'record_type': 'trial_observable',
        'trial_id': 'trial-1',
        'profile_id': 'mtb-h37rv',
        'gene_id': 'Rv0002',
        'gene_name': 'dnaN',
        'pmc_id': '123',
        'section': 'abstract',
        'excerpt_text': 'excerpt',
        'outputs': {
            'extractor_A': {
                'function': 'alpha',
                'functional_category': ['A', 'B'],
                'drug_susc_impact': None,
                'infection_impact': None,
                'essential_in_vitro': True,
                'essential_in_vivo': False,
            },
            'extractor_B': {
                'function': 'beta',
                'functional_category': ['B', 'A'],
                'drug_susc_impact': 'resistance',
                'infection_impact': None,
                'essential_in_vitro': True,
                'essential_in_vivo': False,
            },
            'extractor_C': {
                'function': 'alpha',
                'functional_category': ['C'],
                'drug_susc_impact': None,
                'infection_impact': None,
                'essential_in_vitro': False,
                'essential_in_vivo': False,
            },
            'consensus_D': None,
            'single_A': None,
            'single_B': None,
            'single_C': None,
        },
    }
    bias_dir = _write_bias_run(tmp_path, observables=[observable])

    output_dir = derive_split_vs_not.derive_split_vs_not(
        bias_run_dir=bias_dir,
        run_id='split-test',
        config_path=config_path,
    )

    manifest = json.loads((output_dir / 'manifest.json').read_text())
    assert manifest['parent_bias_run_id'] == 'synthetic-bias'
    assert manifest['parent_experiment_id'] == 'bias-1-vs-3-small'
    assert manifest['n_field_values'] == 6

    split_records = [
        json.loads(line) for line in (output_dir / 'records.jsonl').read_text().splitlines()
    ]
    by_field = {record['field']: record['split_class'] for record in split_records}
    assert by_field['function'] == 'split'
    assert by_field['functional_category'] == 'split'
    assert by_field['drug_susc_impact'] == 'partial'
    assert by_field['infection_impact'] == 'unanimous'
    assert by_field['essential_in_vitro'] == 'split'
    assert by_field['essential_in_vivo'] == 'unanimous'

    aggregate = (output_dir / 'aggregate.csv').read_text().splitlines()
    assert aggregate[0] == (
        'scope,field,n_field_values,split_rate,unanimous_rate,partial_rate'
    )
    overall = aggregate[1].split(',')
    assert overall[0] == 'overall'
    assert overall[2] == '6'
    assert float(overall[3]) == pytest.approx(3 / 6)
    assert float(overall[4]) == pytest.approx(2 / 6)
    assert float(overall[5]) == pytest.approx(1 / 6)


def test_derive_all_null_outputs_are_unanimous(tmp_path, monkeypatch):
    paper_dir = tmp_path / 'paper'
    config_path = paper_dir / 'configs' / 'split-vs-not.yaml'
    config_path.parent.mkdir(parents=True)
    config_path.write_text('experiment_id: split-vs-not\n')
    monkeypatch.setattr(derive_split_vs_not, 'PAPER_DIR', paper_dir)

    observable = {
        'record_type': 'trial_observable',
        'trial_id': 'trial-1',
        'profile_id': 'mtb-h37rv',
        'gene_id': 'Rv0002',
        'gene_name': 'dnaN',
        'section': 'abstract',
        'excerpt_text': 'excerpt',
        'outputs': {
            'extractor_A': None,
            'extractor_B': None,
            'extractor_C': None,
        },
    }
    bias_dir = _write_bias_run(tmp_path, observables=[observable])

    output_dir = derive_split_vs_not.derive_split_vs_not(
        bias_run_dir=bias_dir,
        run_id='split-null-test',
        config_path=config_path,
    )

    split_records = [
        json.loads(line) for line in (output_dir / 'records.jsonl').read_text().splitlines()
    ]
    assert all(record['split_class'] == 'unanimous' for record in split_records)

    overall = (output_dir / 'aggregate.csv').read_text().splitlines()[1].split(',')
    assert float(overall[4]) == 1.0
    assert float(overall[3]) == 0.0
    assert float(overall[5]) == 0.0
