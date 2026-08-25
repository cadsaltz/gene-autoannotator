import csv
import json

import pytest

from experiments.paper.runners import derive_cost_benefit_1_vs_3
from experiments.paper.runners.common import BIOLOGY_FIELDS

AGGREGATE_COLUMNS = (
    'condition',
    'unsupported_rate',
    'supported_rate',
    'null_rate',
    'wall_time_sec_total',
    'wall_time_sec_mean',
    'llm_calls',
    'known_total_tokens',
    'n_field_values',
)
PRIMARY_CONDITIONS = ('single_A', 'single_B', 'single_C', 'consensus_D')
GROUNDEDNESS_LABELS = ('supported', 'unsupported', 'null')


def _metrics(duration_sec: float, *, calls: int = 1, tokens: int = 50) -> dict:
    return {
        'duration_sec': duration_sec,
        'llm_duration_sec': duration_sec * 0.9,
        'usage': {
            'calls': calls,
            'cache_hits': 0,
            'known_total_tokens': tokens,
            'token_usage_complete': True,
            'records': [],
        },
    }


def _trial_observable(trial_id: str) -> dict:
    return {
        'record_type': 'trial_observable',
        'trial_id': trial_id,
        'profile_id': 'mtb-h37rv',
        'gene_id': 'Rv0001',
        'gene_name': 'test',
        'section': 'abstract',
        'excerpt_text': 'Test excerpt about gene function.',
        'outputs': {
            'single_A': None,
            'single_B': None,
            'single_C': None,
            'consensus_D': None,
            'extractor_A': None,
            'extractor_B': None,
            'extractor_C': None,
        },
        'condition_metrics': {
            'single_A': _metrics(1.0, tokens=50),
            'single_B': _metrics(1.0, tokens=50),
            'single_C': _metrics(1.0, tokens=50),
            'consensus_D': _metrics(0.5, tokens=60),
            'extractor_A': _metrics(2.0, tokens=70),
            'extractor_B': _metrics(2.0, tokens=70),
            'extractor_C': _metrics(2.0, tokens=70),
        },
    }


def _field_scores(trial_id: str, condition: str, *, duration_sec: float) -> list[dict]:
    scores = []
    for index, field in enumerate(BIOLOGY_FIELDS):
        scores.append({
            'record_type': 'field_score',
            'trial_id': trial_id,
            'condition': condition,
            'field': field,
            'value': None,
            'groundedness_label': GROUNDEDNESS_LABELS[index % len(GROUNDEDNESS_LABELS)],
            'duration_sec': duration_sec,
            'calls': 1,
            'known_total_tokens': 50,
        })
    return scores


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
        trial_id = observable['trial_id']
        records.append({'record_type': 'trial_meta', 'trial_id': trial_id})
        records.append(observable)
        for condition in PRIMARY_CONDITIONS:
            duration = observable['condition_metrics'][condition]['duration_sec']
            records.extend(_field_scores(trial_id, condition, duration_sec=duration))
    (bias_dir / 'records.jsonl').write_text(
        '\n'.join(json.dumps(record) for record in records) + '\n',
    )
    return bias_dir


def test_derive_cost_benefit_aggregate_and_timing(tmp_path, monkeypatch):
    paper_dir = tmp_path / 'paper'
    config_path = paper_dir / 'configs' / 'cost-benefit-1-vs-3.yaml'
    config_path.parent.mkdir(parents=True)
    config_path.write_text('experiment_id: cost-benefit-1-vs-3\n')
    monkeypatch.setattr(derive_cost_benefit_1_vs_3, 'PAPER_DIR', paper_dir)

    bias_dir = _write_bias_run(
        tmp_path,
        observables=[_trial_observable('trial-1')],
    )

    output_dir = derive_cost_benefit_1_vs_3.derive_cost_benefit_1_vs_3(
        bias_run_dir=bias_dir,
        run_id='cost-test',
        config_path=config_path,
    )

    manifest = json.loads((output_dir / 'manifest.json').read_text())
    assert manifest['parent_bias_run_id'] == 'synthetic-bias'
    assert manifest['parent_experiment_id'] == 'bias-1-vs-3-small'
    assert manifest['crowd_timing_check']['passed'] is True

    with (output_dir / 'aggregate.csv').open(newline='') as handle:
        aggregate_rows = list(csv.DictReader(handle))
    assert list(aggregate_rows[0].keys()) == list(AGGREGATE_COLUMNS)

    by_condition = {row['condition']: row for row in aggregate_rows}
    consensus = by_condition['consensus_D']
    crowd = by_condition['crowd']
    for condition in ('single_A', 'single_B', 'single_C'):
        single = by_condition[condition]
        assert float(consensus['wall_time_sec_total']) < float(single['wall_time_sec_total'])
        assert float(crowd['wall_time_sec_total']) > float(single['wall_time_sec_total'])

    assert float(consensus['wall_time_sec_total']) == pytest.approx(0.5)
    assert float(crowd['wall_time_sec_total']) == pytest.approx(6.5)
    assert int(crowd['llm_calls']) == 4
    assert int(crowd['known_total_tokens']) == 270
    assert crowd['unsupported_rate'] == consensus['unsupported_rate']
    assert float(by_condition['single_A']['wall_time_sec_total']) == pytest.approx(1.0)
    assert int(by_condition['single_A']['n_field_values']) == len(BIOLOGY_FIELDS)


def test_rates_exclude_nulls_except_null_rate():
    scores = [
        {'groundedness_label': 'supported'},
        {'groundedness_label': 'unsupported'},
        {'groundedness_label': 'null'},
        {'groundedness_label': 'null'},
    ]

    assert derive_cost_benefit_1_vs_3._rate(scores, 'supported') == pytest.approx(0.5)
    assert derive_cost_benefit_1_vs_3._rate(scores, 'unsupported') == pytest.approx(0.5)
    assert derive_cost_benefit_1_vs_3._rate(scores, 'null') == pytest.approx(0.5)
