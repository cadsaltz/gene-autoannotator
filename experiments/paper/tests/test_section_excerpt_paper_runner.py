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


def test_expand_trials_creates_one_run_trial_per_chunk(monkeypatch):
    max_chars = 500
    full_text = ('A' * max_chars + '\n\n') * 8
    monkeypatch.setenv('AUTOANNOTATION_SECTION_EXCERPT_MAX_CHARS', str(max_chars))
    monkeypatch.setenv('AUTOANNOTATION_SECTION_RETRIEVAL_THRESHOLD_CHARS', '50000')

    fixture = {
        'trial_id': 'trial-chunk-1',
        'trial_pool': 'biology',
        'profile_id': 'mtb-h37rv',
        'gene_id': 'Rv0001',
        'gene_name': 'dnaA',
        'section': 'results',
        'excerpt_text': full_text,
    }
    expanded = run_bias_1_vs_3.expand_trials_for_excerpts([fixture])

    assert len(expanded) >= 2
    assert all(item['fixture_trial_id'] == 'trial-chunk-1' for item in expanded)
    assert len({item['trial_id'] for item in expanded}) == len(expanded)
    assert all(item['trial_id'].startswith('trial-chunk-1#') for item in expanded)
    assert all(len(item['excerpt_text']) <= max_chars for item in expanded)
    assert all(item['excerpt_preparation']['tier'] == 'chunk' for item in expanded)


def test_biology_trial_records_exact_prompts(tmp_path, monkeypatch):
    full_text = ('Z' * 12000) + 'Rv0001 dnaA replication initiator' + ('Y' * 13000)
    monkeypatch.setenv('AUTOANNOTATION_SECTION_EXCERPT_MAX_CHARS', '1000')
    monkeypatch.setenv('AUTOANNOTATION_SECTION_RETRIEVAL_THRESHOLD_CHARS', '5000')

    trial = {
        'trial_id': 'trial-grep-1',
        'fixture_trial_id': 'trial-grep-1',
        'trial_pool': 'biology',
        'profile_id': 'mtb-h37rv',
        'gene_id': 'Rv0001',
        'gene_name': 'dnaA',
        'section': 'results#grep',
        'excerpt_text': full_text[:1000],
        'excerpt_preparation': {'tier': 'grep', 'part_index': 1, 'part_count': 1, 'chars': 1000},
    }
    layout = dict(build_condition_layout(['model-a', 'model-b', 'model-c']))
    layout['condition_models'] = dict(layout['condition_models'])
    layout['condition_models']['consensus_D'] = 'model-d'

    seen_excerpts: list[str] = []

    class MockLlmHandler:
        def __init__(self, cache_dir):
            self.usage_records = []
            self.prompt_records = []
            self.cache_dir = cache_dir

        def get_llm_gene_info_json(self, gene_id, gene_name, excerpt, model, **kwargs):
            seen_excerpts.append(excerpt)
            prompt = f'PROMPT::{model}::{excerpt[:40]}'
            self.prompt_records.append({
                'role': 'section_summary',
                'model': model,
                'prompt': prompt,
                'sent_to_ollama': True,
            })
            return json.dumps(_MOCK_OUTPUT), 0.01

        def get_llm_consensus_json(self, candidates, *, excerpt, **kwargs):
            self.prompt_records.append({
                'role': 'section_consensus',
                'model': 'model-d',
                'prompt': f'CONSENSUS::{excerpt[:40]}',
                'sent_to_ollama': True,
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

    assert seen_excerpts
    assert all(len(excerpt) <= 1000 for excerpt in seen_excerpts)
    assert 'prompts' in observable
    assert observable['prompts']['extractor_A']['prompt'].startswith('PROMPT::model-a::')
    assert observable['prompts']['consensus_D']['prompt'].startswith('CONSENSUS::')
