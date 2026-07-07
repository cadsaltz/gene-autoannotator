"""Prototype consensus mergers for design comparison tests only.

These implementations are intentionally isolated from the production pipeline.
They model two candidate designs (idea vs idea, not tied to any author):

Design A — rules_only:
  Conservative deterministic merge. 2-of-3 exact agreement required for strings.
  Lone non-null rejected. No LLM at consensus.

Design B — rules_plus_llm:
  Same conservative rules for booleans, identity, lone non-null.
  When 2+ string/array candidates differ without exact agreement, invoke ONE
  batched LLM call (production-shaped) with the excerpt and only unresolved fields.

  hybrid_consensus_per_field() is kept for comparison only.
"""

from __future__ import annotations

import json
import os
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any, Callable

from autoannotation import consensus as production_consensus
from autoannotation import llms
BatchMerger = Callable[[list[dict[str, Any]], list[str]], dict[str, Any]]
LegacyBatchMerger = Callable[[str, list[dict[str, Any]], list[str]], dict[str, Any]]

UNKNOWN_STRINGS = llms.UNKNOWN_STRINGS
MIN_AGREEMENT = 2


DEFAULT_FIELDS = production_consensus.DEFAULT_FIELD_SPECS
FieldSpec = production_consensus.FieldSpec


def normalize_candidate(raw: dict[str, Any]) -> dict[str, Any]:
    return llms.normalize_annotation_fields(raw, require_biology_keys=False)


def _normalize_string(value: str) -> str:
    return ' '.join(str(value).lower().split())


def _category_set(value: Any) -> frozenset[str]:
    if not isinstance(value, list):
        return frozenset()
    return frozenset(
        item.strip().lower()
        for item in value
        if isinstance(item, str) and item.strip()
    )


def _non_null_values(values: list[Any]) -> list[Any]:
    return [value for value in values if not llms.is_unknown_value(value)]


def _majority_exact(values: list[Any], *, normalizer=lambda v: v) -> tuple[Any | None, str]:
    if not values:
        return None, 'all_null'
    normalized = [normalizer(value) for value in values]
    counts = Counter(normalized)
    value, count = counts.most_common(1)[0]
    if count >= MIN_AGREEMENT:
        for original in values:
            if normalizer(original) == value:
                return original, f'{count}/{len(values)}_exact'
    if len(values) == 1:
        return None, 'lone_non_null_rejected'
    return None, 'insufficient_exact_agreement'


def _majority_boolean(values: list[bool]) -> tuple[bool | None, str]:
    if not values:
        return None, 'all_null'
    counts = Counter(values)
    if counts.get(True, 0) >= MIN_AGREEMENT:
        return True, f'{counts[True]}/{len(values)}_true'
    if counts.get(False, 0) >= MIN_AGREEMENT:
        return False, f'{counts[False]}/{len(values)}_false'
    if len(values) == 1:
        return None, 'lone_non_null_rejected'
    return None, 'boolean_conflict'


def _array_intersection(values: list[list[str]]) -> tuple[list[str] | None, str]:
    if not values:
        return None, 'all_null'
    sets = [_category_set(value) for value in values]
    exact, reason = _majority_exact(values, normalizer=_category_set)
    if exact is not None:
        return sorted(_category_set(exact)), reason
    best_pair: tuple[frozenset[str], frozenset[str]] | None = None
    best_jaccard = 0.0
    for i in range(len(sets)):
        for j in range(i + 1, len(sets)):
            union = sets[i] | sets[j]
            if not union:
                continue
            jaccard = len(sets[i] & sets[j]) / len(union)
            if jaccard > best_jaccard:
                best_jaccard = jaccard
                best_pair = (sets[i], sets[j])
    if best_pair is not None and best_jaccard >= 0.8:
        inter = sorted(best_pair[0] & best_pair[1])
        return (inter if inter else None), f'2/{len(values)}_jaccard_intersection'
    if len(values) == 1:
        return None, 'lone_non_null_rejected'
    return None, 'array_conflict'


def _excerpt_tokens(excerpt: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", excerpt.lower())
        if len(token) > 2
    }


def conservative_string_llm_simulator(
    _field_key: str, candidates: list[str], excerpt: str,
) -> str | None:
    """Simulates a well-prompted small model: pick one candidate verbatim or null."""
    excerpt_token_set = _excerpt_tokens(excerpt)
    scored: list[tuple[int, int, str]] = []
    for candidate in candidates:
        candidate_tokens = _excerpt_tokens(candidate)
        overlap = len(candidate_tokens & excerpt_token_set)
        extra_tokens = len(candidate_tokens - excerpt_token_set)
        scored.append((overlap, -extra_tokens, -len(candidate), candidate))
    scored.sort(reverse=True)
    best_overlap, best_extra, _, best = scored[0]
    if best_overlap <= 0:
        return None
    if best_extra < -2:
        return None
    return best


def generative_string_llm_simulator(
    _field_key: str, candidates: list[str], _excerpt: str,
) -> str | None:
    """Simulates an over-creative merger model: synthesizes a new sentence."""
    fragments: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        for clause in re.split(r'[.;]\s*', candidate):
            clause = clause.strip()
            if clause and clause.lower() not in seen:
                seen.add(clause.lower())
                fragments.append(clause)
    if not fragments:
        return None
    return '. '.join(fragments[:3]) + '.'


def conservative_array_llm_simulator(
    _field_key: str, candidates: list[list[str]], excerpt: str,
) -> list[str] | None:
    """Simulates a conservative array merge: intersection of excerpt-supported labels."""
    excerpt_text = excerpt.lower()
    supported: list[frozenset[str]] = []
    for candidate in candidates:
        labels = {
            label.strip().lower()
            for label in candidate
            if label.strip().lower() in excerpt_text
        }
        if labels:
            supported.append(frozenset(labels))
    if len(supported) >= MIN_AGREEMENT:
        inter = supported[0]
        for other in supported[1:]:
            inter &= other
        return sorted(inter) if inter else None
    if len(candidates) == 1:
        return None
    union = set()
    for candidate in candidates:
        union.update(label.strip().lower() for label in candidate if label.strip())
    return sorted(union)


def generative_array_llm_simulator(
    _field_key: str, candidates: list[list[str]], _excerpt: str,
) -> list[str] | None:
    """Simulates an over-creative array merge: union of all labels."""
    union: set[str] = set()
    for candidate in candidates:
        union.update(label.strip().lower() for label in candidate if label.strip())
    return sorted(union)


def ollama_string_merger(field_key: str, candidates: list[str], excerpt: str) -> str | None:
    import ollama

    prompt = f'''
You merge candidate annotation strings for field "{field_key}".

Excerpt:
{excerpt}

Candidates:
{json.dumps(candidates, indent=2)}

Return JSON: {{"merged": string|null}}

Rules:
- merged must be supported by the excerpt.
- Prefer concise wording already present in one candidate.
- You may combine overlapping facts from multiple candidates, but do not add facts absent from the excerpt.
- If candidates conflict or are unsupported, return null.
- Do not mention candidate labels.
'''
    response = ollama.chat(
        model=OLLAMA_CONSENSUS_MODEL,
        messages=[{'role': 'user', 'content': prompt}],
        format={
            'type': 'object',
            'properties': {
                'merged': {'type': ['string', 'null']},
            },
            'required': ['merged'],
            'additionalProperties': False,
        },
        options={'temperature': 0},
    )
    payload = json.loads(response['message']['content'])
    merged = payload.get('merged')
    if merged is None or llms.is_unknown_value(merged):
        return None
    return str(merged).strip()


def ollama_array_merger(field_key: str, candidates: list[list[str]], excerpt: str) -> list[str] | None:
    import ollama

    prompt = f'''
You merge candidate annotation category lists for field "{field_key}".

Excerpt:
{excerpt}

Candidates:
{json.dumps(candidates, indent=2)}

Return JSON: {{"merged": array of strings|null}}

Rules:
- Include only categories explicitly supported by the excerpt.
- Do not add categories present in only one candidate unless clearly supported by the excerpt.
- If uncertain, return null.
'''
    response = ollama.chat(
        model=OLLAMA_CONSENSUS_MODEL,
        format={
            'type': 'object',
            'properties': {
                'merged': {
                    'type': ['array', 'null'],
                    'items': {'type': 'string'},
                },
            },
            'required': ['merged'],
            'additionalProperties': False,
        },
        messages=[{'role': 'user', 'content': prompt}],
        options={'temperature': 0},
    )
    payload = json.loads(response['message']['content'])
    merged = payload.get('merged')
    if merged is None or llms.is_unknown_value(merged):
        return None
    return [str(item).strip() for item in merged if str(item).strip()]


def conservative_batch_llm_simulator(
    excerpt: str,
    candidates: list[dict[str, Any]],
    unresolved_fields: list[str],
) -> dict[str, Any]:
    """Production-shaped batch merge using per-field conservative logic internally."""
    merged: dict[str, Any] = {}
    field_kind = {field.key: field.kind for field in DEFAULT_FIELDS}
    for field_key in unresolved_fields:
        values = _non_null_values([candidate.get(field_key) for candidate in candidates])
        if field_kind.get(field_key) == 'array':
            merged[field_key] = conservative_array_llm_simulator(
                field_key, [list(value) for value in values], excerpt,
            )
        else:
            merged[field_key] = conservative_string_llm_simulator(
                field_key, [str(value) for value in values], excerpt,
            )
    return merged


def ollama_batch_merger(
    candidates: list[dict[str, Any]],
    unresolved_fields: list[str],
) -> dict[str, Any]:
    """One Ollama call to merge all unresolved fields (candidate-only, production-shaped)."""
    import ollama

    candidate_payload = [
        {field_key: candidate.get(field_key) for field_key in unresolved_fields}
        for candidate in candidates
    ]
    prompt = llms.BATCH_CONSENSUS_PROMPT.format(
        candidates_json=json.dumps(candidate_payload, indent=2),
        field_list=', '.join(unresolved_fields),
    )
    properties: dict[str, Any] = {}
    field_kind = {field.key: field.kind for field in DEFAULT_FIELDS}
    for field_key in unresolved_fields:
        if field_kind.get(field_key) == 'array':
            properties[field_key] = {
                'type': ['array', 'null'],
                'items': {'type': 'string'},
            }
        else:
            properties[field_key] = {'type': ['string', 'null']}

    response = ollama.chat(
        model=OLLAMA_CONSENSUS_MODEL,
        messages=[{'role': 'user', 'content': prompt}],
        format={
            'type': 'object',
            'properties': properties,
            'required': unresolved_fields,
            'additionalProperties': False,
        },
        options={'temperature': 0},
    )
    payload = json.loads(response['message']['content'])
    return {field_key: payload.get(field_key) for field_key in unresolved_fields}


def generative_batch_llm_simulator(
    excerpt: str,
    candidates: list[dict[str, Any]],
    unresolved_fields: list[str],
) -> dict[str, Any]:
    """Simulates an over-creative batch merge (shows risk of generative consensus)."""
    field_kind = {field.key: field.kind for field in DEFAULT_FIELDS}
    merged: dict[str, Any] = {}
    for field_key in unresolved_fields:
        values = _non_null_values([candidate.get(field_key) for candidate in candidates])
        if field_kind.get(field_key) == 'array':
            merged[field_key] = generative_array_llm_simulator(
                field_key, [list(value) for value in values], excerpt,
            )
        else:
            merged[field_key] = generative_string_llm_simulator(
                field_key, [str(value) for value in values], excerpt,
            )
    return merged


StringMerger = Callable[[str, list[str], str], str | None]
ArrayMerger = Callable[[str, list[list[str]], str], list[str] | None]

OLLAMA_CONSENSUS_MODEL = os.getenv('CONSENSUS_TEST_MODEL', 'qwen3:8b')
DESIGN_A_LABEL = 'Design A (rules_only)'
DESIGN_B_LABEL = 'Design B (rules_plus_llm)'


def _merge_field_rules_only(
    field: FieldSpec,
    values: list[Any],
    *,
    expected_gene_id: str | None,
    expected_name: str,
) -> tuple[Any | None, str, bool]:
    """Return (value, provenance, needs_llm). needs_llm is True for unresolved strings/arrays."""
    non_null = _non_null_values(values)

    if field.kind == 'identity':
        if field.key == 'gene_id':
            return expected_gene_id, 'supplied_identity', False
        return expected_name, 'supplied_identity', False

    if not non_null:
        return None, 'all_null', False

    if len(non_null) == 1:
        return None, 'lone_non_null_rejected', False

    if field.kind == 'boolean':
        value, reason = _majority_boolean([bool(v) for v in non_null])
        return value, reason, False

    if field.kind == 'array':
        value, reason = _array_intersection([list(v) for v in non_null])
        return value, reason, value is None and reason == 'array_conflict'

    value, reason = _majority_exact(non_null, normalizer=_normalize_string)
    return value, reason, value is None and reason == 'insufficient_exact_agreement'


def deterministic_consensus(
    candidates: list[dict[str, Any]],
    *,
    excerpt: str,
    expected_gene_id: str | None,
    expected_name: str,
    fields: tuple[FieldSpec, ...] = DEFAULT_FIELDS,
) -> tuple[dict[str, Any], dict[str, str]]:
    merged, provenance, _ = production_consensus.deterministic_section_consensus(
        candidates,
        expected_gene_id=expected_gene_id,
        expected_name=expected_name,
        fields=fields,
    )
    return merged, provenance


def _wrap_legacy_batch_merger(
    batch_merger: LegacyBatchMerger,
    excerpt: str,
) -> BatchMerger:
    def wrapped(normalized: list[dict[str, Any]], unresolved_fields: list[str]) -> dict[str, Any]:
        return batch_merger(excerpt, normalized, unresolved_fields)
    return wrapped


def hybrid_consensus_batch(
    candidates: list[dict[str, Any]],
    *,
    excerpt: str,
    expected_gene_id: str | None,
    expected_name: str,
    fields: tuple[FieldSpec, ...] = DEFAULT_FIELDS,
    batch_merger: LegacyBatchMerger | BatchMerger = conservative_batch_llm_simulator,
) -> tuple[dict[str, Any], dict[str, str], int]:
    """Production-shaped Design B: rules first, then one batched LLM call if needed."""
    if batch_merger is ollama_batch_merger:
        production_merger: BatchMerger = batch_merger
    elif batch_merger in (conservative_batch_llm_simulator, generative_batch_llm_simulator):
        production_merger = _wrap_legacy_batch_merger(batch_merger, excerpt)
    else:
        production_merger = batch_merger  # type: ignore[assignment]

    return production_consensus.hybrid_section_consensus(
        candidates,
        excerpt=excerpt,
        expected_gene_id=expected_gene_id,
        expected_name=expected_name,
        fields=fields,
        batch_merger=production_merger,
    )


def hybrid_consensus_per_field(
    candidates: list[dict[str, Any]],
    *,
    excerpt: str,
    expected_gene_id: str | None,
    expected_name: str,
    fields: tuple[FieldSpec, ...] = DEFAULT_FIELDS,
    string_merger: StringMerger = conservative_string_llm_simulator,
    array_merger: ArrayMerger = conservative_array_llm_simulator,
) -> tuple[dict[str, Any], dict[str, str], int]:
    """Per-field LLM merge — kept for comparison against production-shaped batch merge."""
    normalized = [normalize_candidate(candidate) for candidate in candidates]
    merged: dict[str, Any] = {}
    provenance: dict[str, str] = {}

    for field in fields:
        values = [item.get(field.key) for item in normalized]
        non_null = _non_null_values(values)

        if field.kind == 'identity':
            if field.key == 'gene_id':
                merged[field.key] = expected_gene_id
            else:
                merged[field.key] = expected_name
            provenance[field.key] = 'supplied_identity'
            continue

        if not non_null:
            merged[field.key] = None
            provenance[field.key] = 'all_null'
            continue

        if len(non_null) == 1:
            merged[field.key] = None
            provenance[field.key] = 'lone_non_null_rejected'
            continue

        if field.kind == 'boolean':
            value, reason = _majority_boolean([bool(v) for v in non_null])
            merged[field.key] = value
            provenance[field.key] = reason
            continue

        if field.kind == 'string':
            value, reason = _majority_exact(non_null, normalizer=_normalize_string)
            if value is not None:
                merged[field.key] = value
                provenance[field.key] = reason
                continue
            llm_value = string_merger(field.key, [str(v) for v in non_null], excerpt)
            merged[field.key] = None if llms.is_unknown_value(llm_value) else llm_value
            provenance[field.key] = 'llm_string_merge' if merged[field.key] is not None else 'llm_string_null'
            continue

        if field.kind == 'array':
            value, reason = _array_intersection([list(v) for v in non_null])
            if value is not None:
                merged[field.key] = value
                provenance[field.key] = reason
                continue
            llm_value = array_merger(field.key, [list(v) for v in non_null], excerpt)
            merged[field.key] = None if llms.is_unknown_value(llm_value) else llm_value
            provenance[field.key] = 'llm_array_merge' if merged[field.key] is not None else 'llm_array_null'
            continue

        merged[field.key] = None
        provenance[field.key] = 'unsupported_field'

    llm_calls = sum(1 for reason in provenance.values() if reason.startswith('llm_'))
    return merged, provenance, llm_calls


# Default Design B entry point — production-shaped batch merge.
def hybrid_consensus(
    candidates: list[dict[str, Any]],
    *,
    excerpt: str,
    expected_gene_id: str | None,
    expected_name: str,
    fields: tuple[FieldSpec, ...] = DEFAULT_FIELDS,
    batch_merger: BatchMerger = conservative_batch_llm_simulator,
) -> tuple[dict[str, Any], dict[str, str]]:
    merged, provenance, _llm_calls = hybrid_consensus_batch(
        candidates,
        excerpt=excerpt,
        expected_gene_id=expected_gene_id,
        expected_name=expected_name,
        fields=fields,
        batch_merger=batch_merger,
    )
    return merged, provenance


def _field_inputs(candidates: list[dict[str, Any]], field_key: str) -> list[Any]:
    normalized = [normalize_candidate(candidate) for candidate in candidates]
    return [item.get(field_key) for item in normalized]


def _format_candidate_inputs(candidates: list[dict[str, Any]], field_key: str) -> str:
    values = _field_inputs(candidates, field_key)
    parts = []
    for index, value in enumerate(values, start=1):
        parts.append(f'C{index}={json.dumps(value, ensure_ascii=True)}')
    return ' | '.join(parts)


def _divergence_verdict(
    field_key: str,
    design_a: Any,
    design_b: Any,
    design_b_meta: str,
) -> str:
    if design_a == design_b:
        if design_b_meta.startswith('llm_'):
            return 'same (LLM invoked but matched rules path)'
        return 'same'
    if design_a is None and design_b is not None:
        if design_b_meta.startswith('llm_'):
            return 'LLM RECOVERED (rules→null, LLM→value)'
        return 'Design B more permissive'
    if design_a is not None and design_b is None:
        return 'Design B more conservative'
    return 'CONFLICT (different non-null values)'


def format_scenario_report(
    scenario_name: str,
    *,
    excerpt: str,
    candidates: list[dict[str, Any]],
    design_a: dict[str, Any],
    design_a_meta: dict[str, str],
    design_b: dict[str, Any],
    design_b_meta: dict[str, str],
    design_b_backend: str,
    notes: str = '',
    llm_calls: int | None = None,
    unresolved_fields: list[str] | None = None,
) -> str:
    lines = [
        '',
        '=' * 100,
        f'SCENARIO: {scenario_name}',
        '=' * 100,
        '',
        'EXCERPT:',
        excerpt,
        '',
        'RAW CANDIDATES (model outputs before consensus):',
    ]
    for index, candidate in enumerate(candidates, start=1):
        lines.append(f'  Candidate {index}: {json.dumps(normalize_candidate(candidate), ensure_ascii=True)}')
    lines.extend([
        '',
        f'{DESIGN_A_LABEL}  →  no LLM; exact 2-of-3 for strings; lone non-null → null',
        f'{DESIGN_B_LABEL}  →  backend: {design_b_backend}',
        '',
        f'{"FIELD":22} {"INPUTS (C1|C2|C3)":44} {"Design A OUT":26} {"Design B OUT":26} {"VERDICT"}',
        '-' * 100,
    ])
    llm_invoked_fields: list[str] = []
    recovered_fields: list[str] = []
    conflict_fields: list[str] = []
    for key in design_a:
        inputs = _format_candidate_inputs(candidates, key)
        if len(inputs) > 44:
            inputs = inputs[:41] + '...'
        a_val = json.dumps(design_a[key], ensure_ascii=True)
        b_val = json.dumps(design_b.get(key), ensure_ascii=True)
        b_meta = design_b_meta.get(key, '')
        verdict = _divergence_verdict(key, design_a[key], design_b.get(key), b_meta)
        if b_meta.startswith('llm_'):
            llm_invoked_fields.append(key)
        if design_a[key] is None and design_b.get(key) is not None and b_meta.startswith('llm_'):
            recovered_fields.append(key)
        if verdict.startswith('CONFLICT'):
            conflict_fields.append(key)
        lines.append(f'{key:22} {inputs:44} {a_val:26} {b_val:26} {verdict}')

    lines.extend([
        '-' * 100,
        'FIELD-LEVEL META:',
    ])
    for key in design_a:
        lines.append(
            f'  {key:22}  A: {design_a_meta.get(key, ""):28}  B: {design_b_meta.get(key, "")}'
        )

    lines.extend([
        '',
        'SCENARIO VERDICT (is the consensus LLM worth it here?):',
        f'  LLM calls made: {llm_calls if llm_calls is not None else "(unknown)"}',
    ])
    if unresolved_fields is not None:
        lines.append(
            f'  Unresolved fields sent to LLM: {", ".join(unresolved_fields) if unresolved_fields else "(none)"}'
        )
    lines.extend([
        f'  LLM merge invoked for: {", ".join(llm_invoked_fields) if llm_invoked_fields else "(none)"}',
        f'  Fields recovered by LLM that rules-only left null: {", ".join(recovered_fields) if recovered_fields else "(none)"}',
        f'  Conflicting non-null outputs between designs: {", ".join(conflict_fields) if conflict_fields else "(none)"}',
    ])
    if recovered_fields and not conflict_fields:
        lines.append('  → LLM added information rules-only would miss. Review recovered fields against excerpt.')
    elif recovered_fields and conflict_fields:
        lines.append('  → LLM both recovered and conflicted. Manual review required.')
    elif llm_invoked_fields and not recovered_fields:
        lines.append('  → LLM ran but did not beat rules-only on any field. LLM call may not be worth it here.')
    elif not llm_invoked_fields:
        lines.append('  → Rules-only handled everything. No LLM call needed for this scenario.')
    if notes:
        lines.append(f'  Notes: {notes}')
    lines.append('=' * 100)
    return '\n'.join(lines)


def format_merge_report(
    scenario_name: str,
    *,
    deterministic: dict[str, Any],
    deterministic_meta: dict[str, str],
    hybrid: dict[str, Any],
    hybrid_meta: dict[str, str],
    hybrid_label: str = 'Design B',
) -> str:
    """Backward-compatible thin wrapper."""
    return format_scenario_report(
        scenario_name,
        excerpt='',
        candidates=[],
        design_a=deterministic,
        design_a_meta=deterministic_meta,
        design_b=hybrid,
        design_b_meta=hybrid_meta,
        design_b_backend=hybrid_label,
    )
