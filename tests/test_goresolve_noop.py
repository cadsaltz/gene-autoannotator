from goresolve.resolve import has_usable_text, resolve_go_terms


def test_has_usable_text_false_when_both_empty():
    assert has_usable_text(None, None) is False
    assert has_usable_text('', []) is False
    assert has_usable_text('  ', ['']) is False


def test_has_usable_text_true_when_either_present():
    assert has_usable_text('dna repair', None) is True
    assert has_usable_text(None, ['Mitosis']) is True
    assert has_usable_text('', ['  Cell cycle  ']) is True


def test_resolve_noop_returns_skipped_no_text():
    result = resolve_go_terms(
        function=None,
        functional_category=None,
        ontology_path='unused.obo',
        embedder=None,
        ranker_models=[],
    )
    assert result.method == 'skipped_no_text'
    assert result.go_terms == ()
    assert result.shortlist == ()
    assert result.queries == ()
