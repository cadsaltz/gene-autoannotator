import sys
from types import SimpleNamespace

from experiments.paper.runners.groundedness import (
    make_hf_nli_fn, stringify_hypothesis, map_nli_label, score_field_groundedness,
)

def test_map_nli_labels():
    assert map_nli_label('ENTAILMENT') == 'supported'
    assert map_nli_label('NEUTRAL') == 'unsupported'
    assert map_nli_label('CONTRADICTION') == 'unsupported'

def test_score_null_skips_nli():
    calls = []
    def nli(p, h):
        calls.append((p, h))
        return {'label': 'ENTAILMENT', 'score': 0.9}
    out = score_field_groundedness('excerpt', 'function', None, nli)
    assert out['groundedness_label'] == 'null'
    assert calls == []

def test_score_uses_nli():
    excerpt = 'text about dnaN'
    def nli(p, h):
        assert p == excerpt
        assert 'DNA polymerase' in h
        return {
            'label': 'NEUTRAL',
            'score': 0.55,
            'premise_truncated': True,
            'premise_tokens_before': 900,
        }
    out = score_field_groundedness(excerpt, 'function', 'DNA polymerase', nli)
    assert out['groundedness_label'] == 'unsupported'
    assert out['raw_label'] == 'NEUTRAL'
    assert out['premise_truncated'] is True
    assert out['premise_tokens_before'] == 900


def test_hf_nli_preserves_hypothesis_when_premise_is_overlength(monkeypatch):
    calls = []

    class FakeTokenizer:
        model_max_length = 8

        def __call__(self, text, text_pair=None, **kwargs):
            if text_pair is None:
                return {'input_ids': text.split()}
            calls.append((text, text_pair, kwargs))
            return {'input_ids': list(range(self.model_max_length))}

    class FakePipeline:
        tokenizer = FakeTokenizer()

        def __call__(self, inputs, **kwargs):
            self.tokenizer(inputs['text'], inputs['text_pair'], **kwargs)
            return [{'label': 'ENTAILMENT', 'score': 0.99}]

    fake_pipeline = FakePipeline()
    monkeypatch.setitem(
        sys.modules,
        'transformers',
        SimpleNamespace(pipeline=lambda *_args, **_kwargs: fake_pipeline),
    )

    nli = make_hf_nli_fn('fake-nli')
    result = nli('one two three four five six seven eight nine', 'keep this')

    premise, hypothesis, kwargs = calls[0]
    assert premise.startswith('one two')
    assert hypothesis == 'keep this'
    assert kwargs['truncation'] == 'only_first'
    assert kwargs['max_length'] == 8
    assert result['premise_truncated'] is True
    assert result['premise_tokens_before'] == 9
