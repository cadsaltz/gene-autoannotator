import sys
from types import SimpleNamespace

from experiments.paper.runners.groundedness import (
    make_hf_nli_fn,
    stringify_hypothesis,
    map_nli_label,
    score_field_groundedness,
    truncate_premise_for_nli,
    _normalize_pipeline_output,
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


def test_normalize_pipeline_output_accepts_dict_or_list():
    assert _normalize_pipeline_output({'label': 'ENTAILMENT', 'score': 1.0})['label'] == 'ENTAILMENT'
    assert _normalize_pipeline_output([{'label': 'NEUTRAL', 'score': 0.5}])['label'] == 'NEUTRAL'


def test_truncate_premise_preserves_hypothesis_budget():
    class FakeTokenizer:
        def __call__(self, text, add_special_tokens=False, truncation=False):
            return {'input_ids': text.split()}

        def num_special_tokens_to_add(self, pair=False):
            return 3 if pair else 2

        def decode(self, ids, skip_special_tokens=True):
            return ' '.join(ids)

    premise = 'one two three four five six seven eight nine ten'
    hypothesis = 'keep this claim'
    truncated, was_truncated, before = truncate_premise_for_nli(
        FakeTokenizer(), premise, hypothesis, max_length=10,
    )
    # budget = 10 - len(hyp=3) - special(3) = 4 premise tokens
    assert was_truncated is True
    assert before == 10
    assert truncated == 'one two three four'
    assert 'keep' not in truncated


def test_hf_nli_preserves_hypothesis_when_premise_is_overlength(monkeypatch):
    calls = []

    class FakeTokenizer:
        model_max_length = 8

        def __call__(self, text, text_pair=None, add_special_tokens=False, truncation=False, **kwargs):
            if text_pair is None:
                return {'input_ids': text.split()}
            return {'input_ids': list(range(self.model_max_length))}

        def num_special_tokens_to_add(self, pair=False):
            return 2 if pair else 1

        def decode(self, ids, skip_special_tokens=True):
            return ' '.join(ids)

    class FakeModelConfig:
        max_position_embeddings = 8

    class FakePipeline:
        tokenizer = FakeTokenizer()
        model = SimpleNamespace(config=FakeModelConfig())

        def __call__(self, inputs, **kwargs):
            calls.append((inputs, kwargs))
            # Simulate transformers returning a bare dict (ethan's crash mode).
            return {'label': 'ENTAILMENT', 'score': 0.99}

    fake_pipeline = FakePipeline()
    monkeypatch.setitem(
        sys.modules,
        'transformers',
        SimpleNamespace(pipeline=lambda *_args, **_kwargs: fake_pipeline),
    )

    nli = make_hf_nli_fn('fake-nli')
    result = nli('one two three four five six seven eight nine', 'keep this')

    inputs, kwargs = calls[0]
    assert inputs['text_pair'] == 'keep this'
    assert len(inputs['text'].split()) <= 8
    assert kwargs.get('truncation') is True
    assert result['premise_truncated'] is True
    assert result['label'] == 'ENTAILMENT'
