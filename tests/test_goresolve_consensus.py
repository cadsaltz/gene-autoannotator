from goresolve.consensus import agreement_threshold, majority_go_ids


def test_agreement_threshold_three_models_needs_two():
    assert agreement_threshold(3) == 2
    assert agreement_threshold(2) == 1


def test_majority_keeps_ids_at_or_above_threshold():
    votes = [
        ['GO:0000910', 'GO:0000278', 'GO:0007067'],
        ['GO:0000910', 'GO:0000278'],
        ['GO:0000910'],
    ]
    winners = majority_go_ids(votes, n_models=3)
    ids = [w[0] for w in winners]
    assert ids == ['GO:0000910', 'GO:0000278']  # sorted by vote count desc then id
    assert winners[0][1] == '3/3'
    assert winners[1][1] == '2/3'


def test_majority_tie_breaks_by_go_id_asc():
    votes = [
        ['GO:0000002', 'GO:0000001'],
        ['GO:0000002', 'GO:0000001'],
    ]
    winners = majority_go_ids(votes, n_models=2)
    ids = [w[0] for w in winners]
    assert ids == ['GO:0000001', 'GO:0000002']
