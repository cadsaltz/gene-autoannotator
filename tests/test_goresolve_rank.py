from pathlib import Path

from goresolve.embeddings import FakeEmbedder
from goresolve.resolve import resolve_go_terms
from goresolve.types import GoCandidate
from goresolve.rank import build_ranker_prompt, filter_ids_to_shortlist, rank_go_terms


FIXTURE = Path('tests/fixtures/go/mini.obo')


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


def test_ranker_prompt_includes_grain_and_regulation_rules():
    prompt = build_ranker_prompt(
        function='regulates translation and promotes mRNA degradation',
        functional_category=['translation', 'detoxification'],
        shortlist=_shortlist(),
    )
    assert 'regulation of' in prompt.lower()
    assert 'do not select a broad process' in prompt.lower()
    assert 'exact category label' in prompt.lower()
    assert 'molecular_function + biological_process pair' in prompt
    assert 'fewer high-confidence terms' in prompt.lower()


def test_resolve_uses_cleaned_text_for_retrieval_and_ranking():
    prompts = []

    def fake_rank_fn(prompt, model):
        prompts.append(prompt)
        return {'go_terms': [{'id': 'GO:0006412'}]}

    result = resolve_go_terms(
        function='protein synthesis (PMID 12345)',
        functional_category=['translation PMID: 67890'],
        ontology_path=str(FIXTURE),
        embedder=FakeEmbedder(dim=64),
        ranker_models=['m1'],
        rank_fn=fake_rank_fn,
        top_k=10,
        min_cosine=0.05,
    )

    assert result.queries == ('translation', 'protein synthesis')
    assert len(prompts) == 1
    assert 'PMID' not in prompts[0]
    assert '12345' not in prompts[0]
    assert '67890' not in prompts[0]
    assert 'Function: protein synthesis' in prompts[0]
    assert 'Functional categories: translation' in prompts[0]


def test_resolve_skips_when_cleaning_removes_all_text():
    result = resolve_go_terms(
        function='(PMID 12345)',
        functional_category=['PMC5017210'],
        ontology_path='unused.obo',
        embedder=FakeEmbedder(dim=64),
        ranker_models=['m1'],
    )

    assert result.method == 'skipped_no_text'
    assert result.queries == ()


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
