from pathlib import Path

import pytest

from experiments.paper.runners import common


def _items(profile_counts: dict[str, int]) -> list[dict]:
    items = []
    index = 0
    for profile_id, count in profile_counts.items():
        for _ in range(count):
            items.append({
                'trial_id': f'{profile_id}-t{index}',
                'profile_id': profile_id,
            })
            index += 1
    return items


def test_select_trials_default_slice():
    items = [{'trial_id': f't{i}'} for i in range(300)]
    got = common.select_trials(items, 10, max_trials=300)
    assert [x['trial_id'] for x in got] == [f't{i}' for i in range(10)]


def test_select_trials_rejects_zero_and_over_pool():
    items = [{'trial_id': f't{i}'} for i in range(15)]
    with pytest.raises(ValueError):
        common.select_trials(items, 0, max_trials=15)
    with pytest.raises(ValueError):
        common.select_trials(items, 16, max_trials=15)


def test_select_trials_distribution_mixed():
    items = _items({'mtb-h37rv': 10, 'ecoli-k12-mg1655': 10, 'tcruzi-clbrener': 10})
    distribution = {'mtb-h37rv': 2, 'ecoli-k12-mg1655': 3, 'tcruzi-clbrener': 1}
    got = common.select_trials(items, 6, distribution=distribution, seed=1)
    counts = {}
    for item in got:
        counts[item['profile_id']] = counts.get(item['profile_id'], 0) + 1
    assert counts == distribution


def test_parse_distribution_aliases():
    assert common.parse_distribution('mtb:5,ecoli:5,tcruzi:5') == {
        'mtb-h37rv': 5,
        'ecoli-k12-mg1655': 5,
        'tcruzi-clbrener': 5,
    }


def test_field_values_equal_array_order_insensitive():
    assert common.field_values_equal(['A', 'B'], ['b', 'a'], kind='array')


def test_build_condition_layout_grows_with_extractor_count():
    layout = common.build_condition_layout([
        'model-a',
        'model-b',
        'model-c',
        'model-d',
    ])
    assert layout['conditions'] == (
        'extractor_A',
        'extractor_B',
        'extractor_C',
        'extractor_D',
        'consensus_D',
        'single_A',
        'single_B',
        'single_C',
        'single_D',
    )
    assert layout['condition_models']['extractor_D'] == 'model-d'
