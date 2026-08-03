from pathlib import Path

from goresolve.embeddings import FakeEmbedder
from goresolve.resolve import resolve_go_terms


FIXTURE = Path('tests/fixtures/go/mini.obo')


def test_resolve_with_injected_rankers_returns_majority_terms():
    calls = []

    def rank_fn(prompt, model):
        calls.append(model)
        if model == 'm1':
            return {'go_terms': [{'id': 'GO:0000910'}, {'id': 'GO:0000278'}]}
        if model == 'm2':
            return {'go_terms': [{'id': 'GO:0000910'}, {'id': 'GO:0000278'}]}
        return {
            'go_terms': [
                {'id': 'GO:0000910'},
                {'id': 'GO:1234567'},
            ]
        }

    result = resolve_go_terms(
        function='cytokinesis and mitotic cell cycle',
        functional_category=['Cytokinesis', 'Mitosis'],
        ontology_path=str(FIXTURE),
        embedder=FakeEmbedder(dim=64),
        ranker_models=['m1', 'm2', 'm3'],
        rank_fn=rank_fn,
        top_k=10,
        min_cosine=0.05,
    )

    assert result.method == 'rag_llm_majority'
    ids = {term.id for term in result.go_terms}
    assert ids == {'GO:0000910', 'GO:0000278'}
    assert all(term.id in {candidate.id for candidate in result.shortlist} for term in result.go_terms)
    assert calls == ['m1', 'm2', 'm3']


def test_resolve_drops_ancestor_after_majority():
    def rank_fn(prompt, model):
        return {
            'go_terms': [
                {'id': 'GO:0007049'},
                {'id': 'GO:0000278'},
            ]
        }

    result = resolve_go_terms(
        function='cell cycle and mitotic cell cycle',
        functional_category=None,
        ontology_path=str(FIXTURE),
        embedder=FakeEmbedder(dim=64),
        ranker_models=['m1', 'm2', 'm3'],
        rank_fn=rank_fn,
        top_k=10,
        min_cosine=0.05,
    )

    assert [term.id for term in result.go_terms] == ['GO:0000278']
    assert result.notes == 'Dropped 1 ancestor GO terms after majority.'


def test_exact_only_skips_llm_when_rankers_are_disabled():
    result = resolve_go_terms(
        function=None,
        functional_category=['Cytokinesis'],
        ontology_path=str(FIXTURE),
        embedder=FakeEmbedder(dim=64),
        ranker_models=[],
        top_k=10,
        min_cosine=0.05,
    )

    assert result.method == 'exact_only'
    assert [term.id for term in result.go_terms] == ['GO:0000910']
    assert all(term.id in {candidate.id for candidate in result.shortlist} for term in result.go_terms)
    assert result.votes == ()


def test_no_candidates_returns_empty_result(tmp_path):
    result = resolve_go_terms(
        function='unknown biological activity',
        functional_category=None,
        ontology_path=str(tmp_path / 'missing.obo'),
        embedder=FakeEmbedder(dim=64),
        ranker_models=['m1'],
        rank_fn=lambda prompt, model: {'go_terms': [{'id': 'GO:0000910'}]},
        top_k=10,
        min_cosine=0.05,
    )

    assert result.method == 'no_candidates'
    assert result.go_terms == ()
    assert result.shortlist == ()
    assert result.votes == ()
