from goresolve.types import GoCandidate
from goresolve.rank import build_ranker_prompt, filter_ids_to_shortlist, rank_go_terms


def _shortlist():
    return [
        GoCandidate('GO:0000910', 'cytokinesis', 'biological_process', 'cytoplasm division', 1.0, 'exact'),
        GoCandidate('GO:0000278', 'mitotic cell cycle', 'biological_process', 'mitosis progression', 0.8, 'embedding'),
        GoCandidate('GO:0006412', 'translation', 'biological_process', 'protein formation', 0.2, 'embedding'),
    ]


def test_ranker_prompt_lists_only_shortlist_ids():
    prompt = build_ranker_prompt(
        function='cytokinesis during mitosis',
        functional_category=['Cytokinesis', 'Mitosis'],
        shortlist=_shortlist(),
        gene_id=None,
        gene_name=None,
    )
    assert 'GO:0000910' in prompt
    assert 'GO:0000278' in prompt
    assert 'CANDIDATE LIST' in prompt
    assert 'ONLY choose GO IDs from the CANDIDATE LIST' in prompt


def test_filter_drops_hallucinated_ids():
    kept = filter_ids_to_shortlist(
        ['GO:0000910', 'GO:9999999', 'GO:0000278'],
        _shortlist(),
    )
    assert kept == ['GO:0000910', 'GO:0000278']


def test_rank_go_terms_uses_injected_rank_fn():
    def fake_rank_fn(prompt, model):
        return {'go_terms': [{'id': 'GO:0000910'}, {'id': 'GO:9999999'}]}

    ids = rank_go_terms(
        function='x',
        functional_category=['Cytokinesis'],
        shortlist=_shortlist(),
        model='fake-model',
        rank_fn=fake_rank_fn,
    )
    assert ids == ['GO:0000910']
