import json

from experiments.paper.runners import run_bias_1_vs_3
from experiments.paper.runners.common import build_condition_layout

_MOCK_OUTPUT = {
    'gene_id': 'Rv0001',
    'name': 'dnaA',
    'function': 'replication initiator',
    'functional_category': ['DNA replication'],
    'drug_susc_impact': None,
    'infection_impact': None,
    'essential_in_vitro': True,
    'essential_in_vivo': None,
}


def test_biology_trial_uses_prepared_excerpts(tmp_path, monkeypatch):
    full_text = ('Z' * 12000) + 'Rv0001 dnaA replication initiator' + ('Y' * 13000)
    assert len(full_text) >= 25_000

    monkeypatch.setenv('AUTOANNOTATION_SECTION_EXCERPT_MAX_CHARS', '1000')
    monkeypatch.setenv('AUTOANNOTATION_SECTION_RETRIEVAL_THRESHOLD_CHARS', '5000')

    trial = {
        'trial_id': 'trial-grep-1',
        'trial_pool': 'biology',
        'profile_id': 'mtb-h37rv',
        'gene_id': 'Rv0001',
        'gene_name': 'dnaA',
        'section': 'results',
        'excerpt_text': full_text,
    }
    layout = dict(build_condition_layout(['model-a', 'model-b', 'model-c']))
    layout['condition_models'] = dict(layout['condition_models'])
    layout['condition_models']['consensus_D'] = 'model-d'

    seen_excerpts = []

    class MockLlmHandler:
        def __init__(self, cache_dir):
            self.usage_records = []
            self.cache_dir = cache_dir

        def get_llm_gene_info_json(self, gene_id, gene_name, excerpt, model, **kwargs):
            seen_excerpts.append(excerpt)
            return json.dumps(_MOCK_OUTPUT), 0.01

        def get_llm_consensus_json(self, candidates, *, excerpt, **kwargs):
            first = candidates[0]
            if isinstance(first, dict):
                return json.dumps(first), 0.01
            return first, 0.01

    monkeypatch.setattr('autoannotation.llms.LlmHandler', MockLlmHandler)

    observable = run_bias_1_vs_3._run_biology_trial(
        trial,
        layout=layout,
        consensus_model='model-d',
        cache_root=tmp_path / 'cache',
    )

    assert seen_excerpts
    assert all(len(excerpt) < len(full_text) for excerpt in seen_excerpts)
    assert 'excerpt_preparation' in observable
    assert observable['excerpt_preparation']['tier'] == 'grep'
    assert observable['excerpt_preparation']['parts']
    assert all(part['chars'] <= 1000 for part in observable['excerpt_preparation']['parts'])
