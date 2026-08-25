from __future__ import annotations

from typing import Any, Callable

from experiments.paper.runners.common import is_nullish

_NLI_TO_GROUNDEDNESS = {
    'ENTAILMENT': 'supported',
    'NEUTRAL': 'unsupported',
    'CONTRADICTION': 'unsupported',
}


def stringify_hypothesis(field_key: str, value: Any) -> str | None:
    if is_nullish(value):
        return None
    if isinstance(value, bool):
        label = field_key.replace('_', ' ')
        return f'The {label} is {str(value).lower()}.'
    if isinstance(value, list):
        text = ', '.join(str(item) for item in value if item is not None)
        return text if text.strip() else None
    return str(value)


def map_nli_label(raw_label: str) -> str:
    normalized = raw_label.strip().upper()
    if normalized.startswith('LABEL_'):
        normalized = normalized[len('LABEL_') :]
    try:
        return _NLI_TO_GROUNDEDNESS[normalized]
    except KeyError:
        raise ValueError(f'Unknown NLI label: {raw_label!r}') from None


def score_field_groundedness(
    excerpt: str,
    field_key: str,
    value: Any,
    nli_fn: Callable[[str, str], dict[str, Any]],
) -> dict[str, Any]:
    hypothesis = stringify_hypothesis(field_key, value)
    if hypothesis is None:
        return {
            'null': True,
            'raw_label': None,
            'raw_score': None,
            'groundedness_label': 'null',
        }
    result = nli_fn(excerpt, hypothesis)
    raw_label = result['label']
    raw_score = float(result['score'])
    return {
        'null': False,
        'raw_label': raw_label,
        'raw_score': raw_score,
        'groundedness_label': map_nli_label(raw_label),
        **{
            key: result[key]
            for key in ('premise_truncated', 'premise_tokens_before')
            if key in result
        },
    }


def make_hf_nli_fn(model_id: str = 'roberta-large-mnli'):
    from transformers import pipeline

    nli = pipeline('text-classification', model=model_id)
    tokenizer = nli.tokenizer
    max_length = int(tokenizer.model_max_length)
    if max_length > 1_000_000:
        max_length = int(nli.model.config.max_position_embeddings)

    def _fn(premise: str, hypothesis: str):
        premise_tokens_before = len(
            tokenizer(premise, add_special_tokens=False, truncation=False)['input_ids'],
        )
        hypothesis_tokens = len(
            tokenizer(hypothesis, add_special_tokens=False, truncation=False)['input_ids'],
        )
        special_tokens = (
            tokenizer.num_special_tokens_to_add(pair=True)
            if hasattr(tokenizer, 'num_special_tokens_to_add')
            else 4
        )
        out = nli(
            {'text': premise, 'text_pair': hypothesis},
            truncation='only_first',
            max_length=max_length,
        )[0]
        return {
            'label': out['label'],
            'score': float(out['score']),
            'premise_truncated': (
                premise_tokens_before + hypothesis_tokens + special_tokens > max_length
            ),
            'premise_tokens_before': premise_tokens_before,
        }

    return _fn
