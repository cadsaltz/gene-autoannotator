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


def _normalize_pipeline_output(out: Any) -> dict[str, Any]:
    """Transformers pipeline may return a dict or a one-element list."""
    if isinstance(out, list):
        if not out:
            raise ValueError('NLI pipeline returned an empty list')
        out = out[0]
    if not isinstance(out, dict):
        raise TypeError(f'Unexpected NLI output type: {type(out)!r}')
    return out


def truncate_premise_for_nli(
    tokenizer: Any,
    premise: str,
    hypothesis: str,
    *,
    max_length: int,
) -> tuple[str, bool, int]:
    """
    Truncate premise tokens so premise+hypothesis fit in max_length.
    Preserves the full hypothesis (hypothesis is never truncated).
    """
    prem_ids = tokenizer(premise, add_special_tokens=False, truncation=False)['input_ids']
    hyp_ids = tokenizer(hypothesis, add_special_tokens=False, truncation=False)['input_ids']
    if hasattr(tokenizer, 'num_special_tokens_to_add'):
        special = tokenizer.num_special_tokens_to_add(pair=True)
    else:
        special = 4
    budget = max_length - len(hyp_ids) - special
    premise_tokens_before = len(prem_ids)
    if budget <= 0:
        # Hypothesis alone fills the window; keep empty premise rather than crashing.
        return '', True, premise_tokens_before
    if len(prem_ids) <= budget:
        return premise, False, premise_tokens_before
    truncated_ids = prem_ids[:budget]
    truncated_premise = tokenizer.decode(truncated_ids, skip_special_tokens=True)
    return truncated_premise, True, premise_tokens_before


def make_hf_nli_fn(model_id: str = 'roberta-large-mnli'):
    from transformers import pipeline

    nli = pipeline('text-classification', model=model_id)
    tokenizer = nli.tokenizer
    max_length = int(tokenizer.model_max_length)
    if max_length > 1_000_000:
        max_length = int(nli.model.config.max_position_embeddings)
    # RoBERTa position embeddings are typically 514 including specials; keep a safe cap.
    max_length = min(max_length, int(getattr(nli.model.config, 'max_position_embeddings', max_length)))

    def _fn(premise: str, hypothesis: str):
        truncated_premise, premise_truncated, premise_tokens_before = truncate_premise_for_nli(
            tokenizer,
            premise,
            hypothesis,
            max_length=max_length,
        )
        out = _normalize_pipeline_output(
            nli(
                {'text': truncated_premise, 'text_pair': hypothesis},
                truncation=True,
                max_length=max_length,
            ),
        )
        return {
            'label': out['label'],
            'score': float(out['score']),
            'premise_truncated': premise_truncated,
            'premise_tokens_before': premise_tokens_before,
        }

    return _fn
