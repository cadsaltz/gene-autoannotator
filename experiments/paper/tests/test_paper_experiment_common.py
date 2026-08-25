from pathlib import Path
import pytest
from experiments.paper.runners import common


def test_select_trials_default_slice():
    items = [{'trial_id': f't{i}'} for i in range(15)]
    got = common.select_trials(items, 10)
    assert [x['trial_id'] for x in got] == [f't{i}' for i in range(10)]


def test_select_trials_rejects_zero_and_over_pool():
    items = [{'trial_id': f't{i}'} for i in range(15)]
    with pytest.raises(ValueError):
        common.select_trials(items, 0)
    with pytest.raises(ValueError):
        common.select_trials(items, 16)


def test_field_values_equal_array_order_insensitive():
    assert common.field_values_equal(['A', 'B'], ['b', 'a'], kind='array')
