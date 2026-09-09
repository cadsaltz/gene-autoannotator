"""General-passage factual extraction prompts and LLM helpers for paper experiments."""

from __future__ import annotations

import json
import time
from typing import Any

from autoannotation import consensus, llms

GENERAL_EXTRACTION_FIELDS = (
    'direct_answer',
    'supporting_fact',
    'extra_detail',
)

GENERAL_FIELD_SPECS = tuple(
    consensus.FieldSpec(key, 'string') for key in GENERAL_EXTRACTION_FIELDS
)

GENERAL_FIELD_KINDS = {key: 'string' for key in GENERAL_EXTRACTION_FIELDS}


def build_general_extraction_schema() -> dict[str, Any]:
    properties = {
        key: {'type': ['string', 'null']} for key in GENERAL_EXTRACTION_FIELDS
    }
    return {
        'type': 'object',
        'properties': properties,
        'required': list(GENERAL_EXTRACTION_FIELDS),
        'additionalProperties': False,
    }


GENERAL_EXTRACTION_PROMPT = '''
Using ONLY the supplied passage, extract factual fields. Do not use outside knowledge.

Focus question (for direct_answer: answer only if the passage explicitly supports an answer;
otherwise use null):
{focus_question}

Rules:
- Return JSON with exactly these keys: {field_list}
- Use JSON null for any field the passage does NOT explicitly support.
- Do not guess, infer, or use general world knowledge beyond the passage.
- Prefer null over weak or speculative statements.
- direct_answer: concise answer to the focus question when supported by the passage.
- supporting_fact: one other explicit fact stated in the passage (not already used as direct_answer).
- extra_detail: an additional explicit detail (name, date, number, place) from the passage, or null.

Passage:
{excerpt}
'''


GENERAL_CONSENSUS_PROMPT = '''
You merge factual extraction candidate values from different extractor models for the same passage.

Candidate objects (same passage, different extractor models):
{candidates_json}

Merge ONLY these fields: {field_list}

Return JSON with exactly those keys. Use null for any field you cannot reconcile from the candidates.

Rules:
- Reconcile only from the candidate values provided. You do not have access to the source passage.
- When multiple candidates agree on the same fact (exactly or as paraphrases), return that fact using concise wording drawn from the candidates.
- When one candidate value clearly matches the majority (2 of 3 or more), prefer that value.
- You may combine overlapping meaning from multiple candidates for the same field using concise wording.
- Do not add facts not present in any candidate.
- If candidates describe incompatible facts for a field with no clear majority, return null for that field.
- Prefer concise phrasing drawn from the candidates.
'''


def build_general_extraction_prompt(*, excerpt: str, focus_question: str) -> str:
    return GENERAL_EXTRACTION_PROMPT.format(
        focus_question=focus_question.strip(),
        field_list=', '.join(GENERAL_EXTRACTION_FIELDS),
        excerpt=excerpt.strip(),
    )


def normalize_general_output(raw: Any) -> dict[str, Any]:
    if isinstance(raw, str):
        raw = json.loads(raw)
    if not isinstance(raw, dict):
        raise TypeError(f'general extraction output must be a JSON object, got {type(raw).__name__}')
    normalized: dict[str, Any] = {}
    for key in GENERAL_EXTRACTION_FIELDS:
        value = raw.get(key)
        normalized[key] = None if llms.is_unknown_value(value) else value
    return normalized


def finalize_general_output(raw: Any, *, model: str = 'unknown') -> str:
    if isinstance(raw, dict):
        parsed = raw
    else:
        parsed = llms.parse_response_json(str(raw), role='general_extraction', model=model)
    return json.dumps(normalize_general_output(parsed))


def _batch_consensus_schema(unresolved_fields: list[str]) -> dict[str, Any]:
    return {
        'type': 'object',
        'properties': {
            key: {'type': ['string', 'null']} for key in unresolved_fields
        },
        'required': unresolved_fields,
        'additionalProperties': False,
    }


def get_llm_general_extraction_json(
    handler: llms.LlmHandler,
    *,
    excerpt: str,
    focus_question: str,
    model: str,
    retry: bool = True,
) -> tuple[str, float]:
    json_schema = build_general_extraction_schema()
    prompt = build_general_extraction_prompt(
        excerpt=excerpt,
        focus_question=focus_question,
    )

    cached_response, cached_dur = handler._read_cache(model, prompt, json_schema)
    if cached_response is not None:
        handler._record_prompt(
            'general_extraction', model, prompt, sent_to_ollama=False,
        )
        handler._record_usage(
            'general_extraction', model, cached_dur, cache_hit=True,
            usage=handler._read_cache_usage(model, prompt, json_schema),
        )
        return finalize_general_output(cached_response, model=model), cached_dur

    try:
        handler._record_prompt(
            'general_extraction', model, prompt, sent_to_ollama=True,
        )
        response = llms.ollama_chat(
            model=model,
            messages=[{'role': 'user', 'content': prompt}],
            json_schema=json_schema,
            role='general_extraction',
        )
        response_text = llms.chat_response_content(
            response, role='general_extraction', model=model,
        )
        duration_sec = response['total_duration'] / 1_000_000_000
        normalized = finalize_general_output(response_text, model=model)
        usage = handler._usage_from_response(response, duration_sec)
        handler._record_usage('general_extraction', model, duration_sec, usage=usage)
        handler._write_cache(model, prompt, json_schema, normalized, duration_sec, usage=usage)
        return normalized, duration_sec
    except (KeyError, RuntimeError, json.JSONDecodeError, TypeError) as exc:
        if retry:
            return get_llm_general_extraction_json(
                handler,
                excerpt=excerpt,
                focus_question=focus_question,
                model=model,
                retry=False,
            )
        raise RuntimeError(f'Failed to get general extraction from {model}') from exc


def get_llm_general_consensus_json(
    handler: llms.LlmHandler,
    candidates: list[dict[str, Any]],
    *,
    excerpt: str,
    model: str,
    retry: bool = True,
) -> tuple[str, float]:
    """Merge general extraction candidates under trust-the-extractors.

    ``hybrid_section_consensus`` always runs biology ``normalize_annotation_fields``,
    which drops ``direct_answer`` / ``supporting_fact`` / ``extra_detail``. Map those
    keys onto temporary biology string slots for the merge, then map back.

    ``excerpt`` is accepted for API compatibility with the runner but is **not**
    passed into hybrid validation: the general consensus prompt is candidate-only
    (same trust-the-extractors rule as biology batch consensus).
    """
    if len(candidates) < 2:
        raise ValueError('consensus requires at least two candidate JSON objects')

    del excerpt  # candidate-only merge; do not excerpt-gate general consensus

    normalized_candidates = [
        normalize_general_output(candidate) for candidate in candidates
    ]

    # Biology string slots that survive normalize_annotation_fields.
    slot_keys = ('function', 'drug_susc_impact', 'infection_impact')
    if len(GENERAL_EXTRACTION_FIELDS) > len(slot_keys):
        raise ValueError('GENERAL_EXTRACTION_FIELDS longer than available biology slots')
    slot_by_field = {
        field_key: slot_keys[index]
        for index, field_key in enumerate(GENERAL_EXTRACTION_FIELDS)
    }
    field_by_slot = {slot: field_key for field_key, slot in slot_by_field.items()}
    mapped_candidates = [
        {
            slot_by_field[field_key]: candidate.get(field_key)
            for field_key in GENERAL_EXTRACTION_FIELDS
        }
        for candidate in normalized_candidates
    ]
    mapped_fields = tuple(
        consensus.FieldSpec(slot_by_field[field_key], 'string')
        for field_key in GENERAL_EXTRACTION_FIELDS
    )

    def batch_merger(normalized: list[dict[str, Any]], unresolved_fields: list[str]):
        # unresolved_fields are biology slots; prompt/show general field names.
        display_fields = [field_by_slot[key] for key in unresolved_fields]
        cache_prompt = GENERAL_CONSENSUS_PROMPT.format(
            candidates_json=json.dumps(
                [
                    {
                        field_by_slot[key]: item.get(key)
                        for key in unresolved_fields
                    }
                    for item in normalized
                ],
                indent=2,
            ),
            field_list=', '.join(display_fields),
        )
        batch_schema = _batch_consensus_schema(display_fields)
        cached_payload, cached_dur = handler._load_cached_json(
            model, cache_prompt, batch_schema, role='general_consensus',
        )
        if cached_payload is not None:
            handler._record_prompt(
                'general_consensus', model, cache_prompt, sent_to_ollama=False,
            )
            handler._record_usage(
                'general_consensus', model, cached_dur, cache_hit=True,
                usage=handler._read_cache_usage(model, cache_prompt, batch_schema),
            )
            return {
                slot_by_field[field_key]: cached_payload.get(field_key)
                for field_key in display_fields
            }

        handler._record_prompt(
            'general_consensus', model, cache_prompt, sent_to_ollama=True,
        )
        response = llms.ollama_chat(
            model=model,
            messages=[{'role': 'user', 'content': cache_prompt}],
            json_schema=batch_schema,
            role='general_consensus',
        )
        response_text = llms.chat_response_content(
            response, role='general_consensus', model=model,
        )
        duration_sec = response['total_duration'] / 1_000_000_000
        parsed = llms.parse_response_json(response_text, role='general_consensus', model=model)
        usage = handler._usage_from_response(response, duration_sec)
        handler._record_usage('general_consensus', model, duration_sec, usage=usage)
        handler._write_cache(
            model, cache_prompt, batch_schema,
            json.dumps(parsed), duration_sec, usage=usage,
        )
        return {
            slot_by_field[field_key]: parsed.get(field_key)
            for field_key in display_fields
        }

    start = time.perf_counter()
    try:
        merged_slots, _provenance, _llm_calls = consensus.hybrid_section_consensus(
            mapped_candidates,
            excerpt=None,
            expected_gene_id=None,
            expected_name='',
            fields=mapped_fields,
            organism_profile=None,
            field_defs_profile=None,
            batch_merger=batch_merger,
        )
    except (KeyError, ValueError, RuntimeError) as exc:
        if retry:
            return get_llm_general_consensus_json(
                handler,
                candidates,
                excerpt='',
                model=model,
                retry=False,
            )
        raise RuntimeError(f'Failed to get general consensus from {model}') from exc

    merged = {
        field_key: merged_slots.get(slot_by_field[field_key])
        for field_key in GENERAL_EXTRACTION_FIELDS
    }
    duration_sec = time.perf_counter() - start
    return json.dumps(normalize_general_output(merged)), duration_sec
