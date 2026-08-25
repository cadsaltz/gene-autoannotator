from experiments.paper.runners.split_classify import classify_extractor_split


def test_unanimous_all_equal():
    assert classify_extractor_split({'A': 'foo', 'B': 'foo', 'C': 'foo'}, kind='string') == 'unanimous'


def test_split_two_distinct_non_null():
    assert classify_extractor_split({'A': 'foo', 'B': 'bar', 'C': 'foo'}, kind='string') == 'split'


def test_partial_single_non_null():
    assert classify_extractor_split({'A': 'foo', 'B': None, 'C': None}, kind='string') == 'partial'


def test_unanimous_all_null():
    assert classify_extractor_split({'A': None, 'B': None, 'C': None}, kind='string') == 'unanimous'
