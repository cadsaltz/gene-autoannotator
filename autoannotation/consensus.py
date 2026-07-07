"""Section-level consensus merge: deterministic rules + optional batched LLM (candidate-only)."""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any, Callable

from . import field_defs
from . import llms

MIN_AGREEMENT = 2
STRING_PARAPHRASE_JACCARD = 0.35
ARRAY_PARAPHRASE_JACCARD = 0.50
FUZZY_DETERMINISTIC_STRING = 0.85
POST_LLM_CANDIDATE_JACCARD = 0.50
POST_LLM_MIN_SHARED_CANDIDATE_TOKENS = 3
POST_LLM_MIN_EXCERPT_OVERLAP = 1
POST_LLM_MAX_EXTRA_TOKENS = 2

BatchMerger = Callable[[list[dict[str, Any]], list[str]], dict[str, Any]]


@dataclass(frozen=True)
class FieldSpec:
    key: str
    kind: str  # identity | boolean | string | array


DEFAULT_FIELD_SPECS = (
    FieldSpec('gene_id', 'identity'),
    FieldSpec('name', 'identity'),
    FieldSpec('function', 'string'),
    FieldSpec('functional_category', 'array'),
    FieldSpec('drug_susc_impact', 'string'),
    FieldSpec('infection_impact', 'string'),
    FieldSpec('essential_in_vitro', 'boolean'),
    FieldSpec('essential_in_vivo', 'boolean'),
)


def _field_kind(field_def: field_defs.AnnotationFieldDef) -> str:
    if field_def.type == 'boolean':
        return 'boolean'
    if field_def.type == 'array:string':
        return 'array'
    return 'string'


def field_specs_from_profile(*, field_defs_profile=None, organism_profile=None) -> tuple[FieldSpec, ...]:
    profile = field_defs_profile or organism_profile
    if profile is None:
        raise ValueError('field_defs_profile or organism_profile is required')
    specs = [
        FieldSpec('gene_id', 'identity'),
        FieldSpec('name', 'identity'),
    ]
    for field_def in field_defs.llm_schema_fields(profile):
        specs.append(FieldSpec(field_def.key, _field_kind(field_def)))
    return tuple(specs)


def _normalize_string(value: str) -> str:
    return ' '.join(str(value).lower().split())


def _content_tokens(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r'[a-z0-9]+', str(text).lower())
        if len(token) > 2
    }


def _non_null_values(values: list[Any]) -> list[Any]:
    return [value for value in values if not llms.is_unknown_value(value)]


def _category_set(value: Any) -> frozenset[str]:
    if not isinstance(value, list):
        return frozenset()
    return frozenset(
        item.strip().lower()
        for item in value
        if isinstance(item, str) and item.strip()
    )


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
    best_jaccard = 0.0
    best_inter: frozenset[str] | None = None
    for i in range(len(sets)):
        for j in range(i + 1, len(sets)):
            union = sets[i] | sets[j]
            if not union:
                continue
            jaccard = len(sets[i] & sets[j]) / len(union)
            if jaccard > best_jaccard:
                best_jaccard = jaccard
                best_inter = sets[i] & sets[j]
    if best_inter is not None and best_jaccard >= 0.8:
        inter = sorted(best_inter)
        return (inter if inter else None), f'2/{len(values)}_jaccard_intersection'
    if len(values) == 1:
        return None, 'lone_non_null_rejected'
    return None, 'array_conflict'


def _merge_field_rules_only(
    field: FieldSpec,
    values: list[Any],
    *,
    expected_gene_id: str | None,
    expected_name: str,
) -> tuple[Any | None, str, bool]:
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


def _normalize_candidates(
    candidates: list[Any],
    *,
    organism_profile=None,
    field_defs_profile=None,
) -> list[dict[str, Any]]:
    normalized = []
    for index, candidate in enumerate(candidates):
        if isinstance(candidate, str):
            try:
                parsed = json.loads(candidate)
            except json.JSONDecodeError as exc:
                preview = candidate[:120].replace('\n', ' ')
                raise ValueError(
                    f'Consensus candidate {index} is not valid JSON: {exc}; preview={preview!r}'
                ) from exc
            if not isinstance(parsed, dict):
                raise ValueError(
                    f'Consensus candidate {index} must be a JSON object, got {type(parsed).__name__}'
                )
        else:
            parsed = candidate
        normalized.append(
            llms.normalize_annotation_fields(
                parsed,
                organism_profile=organism_profile,
                field_defs_profile=field_defs_profile,
            )
        )
    return normalized


def deterministic_section_consensus(
    candidates: list[Any],
    *,
    expected_gene_id: str | None,
    expected_name: str,
    fields: tuple[FieldSpec, ...] = DEFAULT_FIELD_SPECS,
    organism_profile=None,
    field_defs_profile=None,
) -> tuple[dict[str, Any], dict[str, str], list[str]]:
    normalized = _normalize_candidates(
        candidates,
        organism_profile=organism_profile,
        field_defs_profile=field_defs_profile,
    )
    merged: dict[str, Any] = {}
    provenance: dict[str, str] = {}
    unresolved: list[str] = []

    for field in fields:
        values = [item.get(field.key) for item in normalized]
        value, reason, needs_llm = _merge_field_rules_only(
            field,
            values,
            expected_gene_id=expected_gene_id,
            expected_name=expected_name,
        )
        merged[field.key] = value
        provenance[field.key] = reason
        if needs_llm:
            unresolved.append(field.key)

    return merged, provenance, unresolved


def token_jaccard(left: str, right: str) -> float:
    left_tokens = _content_tokens(left)
    right_tokens = _content_tokens(right)
    union = left_tokens | right_tokens
    if not union:
        return 1.0
    return len(left_tokens & right_tokens) / len(union)


def _best_pairwise_jaccard(values: list[str]) -> float:
    best = 0.0
    for i in range(len(values)):
        for j in range(i + 1, len(values)):
            best = max(best, token_jaccard(values[i], values[j]))
    return best


def _best_array_pairwise_jaccard(values: list[list[str]]) -> float:
    sets = [_category_set(value) for value in values]
    best = 0.0
    for i in range(len(sets)):
        for j in range(i + 1, len(sets)):
            union = sets[i] | sets[j]
            if not union:
                continue
            best = max(best, len(sets[i] & sets[j]) / len(union))
    return best


def _field_is_llm_eligible(field: FieldSpec, non_null_values: list[Any]) -> bool:
    if field.kind == 'string':
        strings = [str(value) for value in non_null_values]
        if _best_pairwise_jaccard(strings) >= STRING_PARAPHRASE_JACCARD:
            return True
        shared = (
            set.intersection(*[_content_tokens(value) for value in strings])
            if strings else set()
        )
        return len(shared) >= 2
    if field.kind == 'array':
        arrays = [list(value) for value in non_null_values]
        if any(_category_set(arrays[0]) & _category_set(other) for other in arrays[1:]):
            return True
        return _best_array_pairwise_jaccard(arrays) >= ARRAY_PARAPHRASE_JACCARD
    return False


def filter_llm_eligible_fields(
    candidates: list[dict[str, Any]],
    *,
    unresolved: list[str],
    fields: tuple[FieldSpec, ...],
) -> list[str]:
    field_by_key = {field.key: field for field in fields}
    eligible: list[str] = []
    for field_key in unresolved:
        field = field_by_key[field_key]
        values = _non_null_values([candidate.get(field_key) for candidate in candidates])
        if _field_is_llm_eligible(field, values):
            eligible.append(field_key)
    return eligible


def apply_fuzzy_deterministic_strings(
    merged: dict[str, Any],
    provenance: dict[str, str],
    candidates: list[dict[str, Any]],
    *,
    unresolved: list[str],
    fields: tuple[FieldSpec, ...],
) -> tuple[dict[str, Any], dict[str, str], list[str]]:
    field_by_key = {field.key: field for field in fields}
    still_unresolved = list(unresolved)
    for field_key in list(still_unresolved):
        field = field_by_key[field_key]
        if field.kind != 'string':
            continue
        values = [str(v) for v in _non_null_values([c.get(field_key) for c in candidates])]
        if len(values) < 2:
            continue
        best_score = 0.0
        best_value = None
        for i in range(len(values)):
            for j in range(i + 1, len(values)):
                score = token_jaccard(values[i], values[j])
                if score > best_score:
                    best_score = score
                    best_value = values[i] if len(values[i]) >= len(values[j]) else values[j]
        if best_score >= FUZZY_DETERMINISTIC_STRING and best_value is not None:
            merged[field_key] = best_value
            provenance[field_key] = 'fuzzy_deterministic'
            still_unresolved.remove(field_key)
    return merged, provenance, still_unresolved


def _string_traceable_to_candidates(value: str, candidates: list[str]) -> bool:
    for candidate in candidates:
        if token_jaccard(value, candidate) >= POST_LLM_CANDIDATE_JACCARD:
            return True
    candidate_union = set()
    for candidate in candidates:
        candidate_union |= _content_tokens(candidate)
    return len(_content_tokens(value) & candidate_union) >= POST_LLM_MIN_SHARED_CANDIDATE_TOKENS


def _string_supported_by_excerpt(value: str, excerpt: str) -> bool:
    value_tokens = _content_tokens(value)
    excerpt_tokens = _content_tokens(excerpt)
    overlap = value_tokens & excerpt_tokens
    if len(overlap) < POST_LLM_MIN_EXCERPT_OVERLAP:
        return False
    extra = value_tokens - excerpt_tokens
    return len(extra) <= POST_LLM_MAX_EXTRA_TOKENS


def validate_llm_batch_result(
    batch_result: dict[str, Any],
    *,
    excerpt: str | None,
    candidates: list[dict[str, Any]],
    field_keys: list[str],
    fields: tuple[FieldSpec, ...],
) -> dict[str, Any]:
    field_by_key = {field.key: field for field in fields}
    validated: dict[str, Any] = {}
    for field_key in field_keys:
        field = field_by_key[field_key]
        value = batch_result.get(field_key)
        if llms.is_unknown_value(value):
            validated[field_key] = None
            continue
        if field.kind == 'string':
            strings = [str(v) for v in _non_null_values([c.get(field_key) for c in candidates])]
            text = str(value).strip()
            if not _string_traceable_to_candidates(text, strings):
                validated[field_key] = None
                continue
            if excerpt is not None and not _string_supported_by_excerpt(text, excerpt):
                validated[field_key] = None
                continue
            validated[field_key] = text
            continue
        if field.kind == 'array':
            labels = [str(item).strip() for item in value if str(item).strip()]
            candidate_union = set()
            for candidate in candidates:
                raw = candidate.get(field_key)
                if isinstance(raw, list):
                    candidate_union.update(
                        label.strip().lower() for label in raw if str(label).strip()
                    )
            kept = [label for label in labels if label.strip().lower() in candidate_union]
            if excerpt is not None:
                kept = [label for label in kept if label.lower() in excerpt.lower()]
            validated[field_key] = kept if kept else None
            continue
        validated[field_key] = value
    return validated


def hybrid_section_consensus(
    candidates: list[Any],
    *,
    excerpt: str | None = None,
    expected_gene_id: str | None,
    expected_name: str,
    fields: tuple[FieldSpec, ...] = DEFAULT_FIELD_SPECS,
    organism_profile=None,
    field_defs_profile=None,
    batch_merger: BatchMerger | None = None,
) -> tuple[dict[str, Any], dict[str, str], int]:
    normalized = _normalize_candidates(
        candidates,
        organism_profile=organism_profile,
        field_defs_profile=field_defs_profile,
    )
    merged, provenance, unresolved = deterministic_section_consensus(
        candidates,
        expected_gene_id=expected_gene_id,
        expected_name=expected_name,
        fields=fields,
        organism_profile=organism_profile,
        field_defs_profile=field_defs_profile,
    )
    merged, provenance, unresolved = apply_fuzzy_deterministic_strings(
        merged, provenance, normalized, unresolved=unresolved, fields=fields,
    )

    llm_eligible = filter_llm_eligible_fields(
        normalized, unresolved=unresolved, fields=fields,
    )
    for field_key in unresolved:
        if field_key not in llm_eligible:
            merged[field_key] = None
            provenance[field_key] = 'semantic_conflict'

    if not llm_eligible or batch_merger is None:
        return merged, provenance, 0

    batch_result = batch_merger(normalized, llm_eligible)
    validated = validate_llm_batch_result(
        batch_result,
        excerpt=excerpt,
        candidates=normalized,
        field_keys=llm_eligible,
        fields=fields,
    )
    for field_key in llm_eligible:
        llm_value = validated.get(field_key)
        if llms.is_unknown_value(llm_value):
            merged[field_key] = None
            provenance[field_key] = 'llm_batch_null'
        else:
            merged[field_key] = llm_value
            provenance[field_key] = 'llm_batch_merge'
    return merged, provenance, 1
