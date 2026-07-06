"""Section-level consensus merge: deterministic rules + optional batched LLM (candidate-only)."""

from __future__ import annotations

from dataclasses import dataclass

from . import field_defs


@dataclass(frozen=True)
class FieldSpec:
    key: str
    kind: str  # identity | boolean | string | array


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
