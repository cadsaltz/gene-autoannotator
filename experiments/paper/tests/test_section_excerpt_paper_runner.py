import json
from typing import Any

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


def test_biology_trial_merges_multi_part_chunk_outputs(tmp_path, monkeypatch):
    max_chars = 500
    full_text = ('A' * max_chars + '\n\n') * 8
    assert len(full_text) > max_chars

    monkeypatch.setenv('AUTOANNOTATION_SECTION_EXCERPT_MAX_CHARS', str(max_chars))
    monkeypatch.setenv('AUTOANNOTATION_SECTION_RETRIEVAL_THRESHOLD_CHARS', '50000')

    trial = {
        'trial_id': 'trial-chunk-merge-1',
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
    conditions = layout['conditions']

    gene_info_calls: list[tuple[str, str]] = []
    consensus_calls: list[dict[str, Any]] = []

    class MockLlmHandler:
        def __init__(self, cache_dir):
            self.usage_records = []
            self.cache_dir = cache_dir

        def get_llm_gene_info_json(self, gene_id, gene_name, excerpt, model, **kwargs):
            self.usage_records.append({'total_tokens': 10})
            gene_info_calls.append((excerpt, str(self.cache_dir)))
            return json.dumps(_MOCK_OUTPUT), 0.01

        def get_llm_consensus_json(self, candidates, *, excerpt, **kwargs):
            self.usage_records.append({'total_tokens': 10})
            consensus_calls.append({
                'candidate_count': len(candidates),
                'excerpt_len': len(excerpt),
                'cache_dir': str(self.cache_dir),
            })
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

    prep = observable['excerpt_preparation']
    assert prep['tier'] == 'chunk'
    assert len(prep['parts']) >= 2
    assert all(part['chars'] <= max_chars for part in prep['parts'])

    assert gene_info_calls
    assert all(len(excerpt) <= max_chars for excerpt, _ in gene_info_calls)

    part_cache_dirs = {
        call['cache_dir']
        for call in consensus_calls
        if '/part' in call['cache_dir']
    }
    merge_cache_dirs = {
        call['cache_dir']
        for call in consensus_calls
        if call['cache_dir'].endswith('/merge')
    }
    assert len(part_cache_dirs) >= 2
    assert merge_cache_dirs == {str(tmp_path / 'cache' / 'merge')}

    part_consensus_calls = [
        call for call in consensus_calls if '/part' in call['cache_dir']
    ]
    merge_consensus_calls = [
        call for call in consensus_calls if call['cache_dir'].endswith('/merge')
    ]
    assert len(part_consensus_calls) == len(prep['parts'])
    assert len(merge_consensus_calls) == len(conditions)
    assert all(call['candidate_count'] == len(prep['parts']) for call in merge_consensus_calls)

    assert '\n\n---\n\n' in observable['excerpt_text']
    assert all(
        observable['condition_metrics'][condition]['usage']['calls'] >= len(prep['parts']) + 1
        for condition in conditions
    )
