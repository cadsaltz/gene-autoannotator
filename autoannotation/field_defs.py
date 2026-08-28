import re
from dataclasses import asdict, dataclass

RESERVED_FIELD_KEYS = frozenset({
    'gene_id',
    'name',
    'rv_id',
    'annotation_notes',
    'annotation_metadata',
    'go_terms',
})
FIELD_KEY_PATTERN = re.compile(r'^[a-z][a-z0-9_]*$')

VALID_FIELD_TYPES = frozenset({'string', 'boolean', 'array:string'})
VALID_INFERENCE_STRATEGIES = frozenset({'paper_llm', 'go_terms', 'essentiality_db'})


@dataclass(frozen=True)
class AnnotationFieldDef:
    key: str
    label: str
    description: str
    type: str
    required: bool
    inference_strategy: str
    ortholog_allowed: bool

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_mapping(cls, payload):
        return cls(
            key=payload['key'],
            label=payload['label'],
            description=payload['description'],
            type=payload.get('type', 'string'),
            required=bool(payload.get('required', False)),
            inference_strategy=payload.get('inference_strategy', 'paper_llm'),
            ortholog_allowed=bool(payload.get('ortholog_allowed', False)),
        )


REQUIRED_DEFAULT_FIELDS = (
    AnnotationFieldDef(
        key='function',
        label='Gene product function',
        description=(
            'What this gene product does for the cell (one or two concise sentences). '
            'State the gene-specific mechanism and whether it performs vs regulates a '
            'process. This is not a summary of the paper, section, methods, or pathway '
            'panel. Do not describe other genes. Do not stuff category labels or citation '
            'IDs into this field; put citations only if essential to the claim. Use null '
            'if the excerpt does not explicitly support a claim about this gene product.'
        ),
        type='string',
        required=True,
        inference_strategy='paper_llm',
        ortholog_allowed=True,
    ),
    AnnotationFieldDef(
        key='functional_category',
        label='Functional category (GO-oriented tags)',
        description=(
            'One or more short GO-oriented functional tags (about 2–6 words each). Prefer '
            'Gene-Ontology-friendly phrasing such as "regulation of translation", '
            '"protein folding", "copper ion transport", "mRNA export from nucleus". '
            'If the gene regulates a process, say "regulation of X" rather than bare "X". '
            'One concept per list item. This is not a summary of the excerpt or paper. '
            'Do not include PMIDs, PMC IDs, locus IDs, or long sentences. Prefer a small '
            'set of high-confidence labels over a long speculative list. Use null if not '
            'supported.'
        ),
        type='array:string',
        required=True,
        inference_strategy='go_terms',
        ortholog_allowed=False,
    ),
)

BUILTIN_OPTIONAL_FIELD_TEMPLATES = (
    AnnotationFieldDef(
        key='drug_susc_impact',
        label='Drug susceptibility impact',
        description=(
            'Impact on {species_name} drug susceptibility (one or two concise sentences). '
            'Only state effects explicitly reported in the excerpt. Use null otherwise.'
        ),
        type='string',
        required=False,
        inference_strategy='paper_llm',
        ortholog_allowed=False,
    ),
    AnnotationFieldDef(
        key='infection_impact',
        label='Infection impact',
        description=(
            'Impact on {species_name} infection (one or two concise sentences). '
            'Only state effects explicitly reported in the excerpt. Use null otherwise.'
        ),
        type='string',
        required=False,
        inference_strategy='paper_llm',
        ortholog_allowed=False,
    ),
    AnnotationFieldDef(
        key='essential_in_vitro',
        label='Essential in vitro',
        description=(
            'Whether the gene is essential for {species_name} survival in vitro. '
            'Use true or false only when the excerpt reports direct experimental evidence '
            '(e.g., deletion, transposon, CRISPRi). Otherwise use null.'
        ),
        type='boolean',
        required=False,
        inference_strategy='paper_llm',
        ortholog_allowed=False,
    ),
    AnnotationFieldDef(
        key='essential_in_vivo',
        label='Essential in vivo',
        description=(
            'Whether the gene is essential for {species_name} survival in vivo. '
            'Use true or false only when the excerpt reports direct experimental evidence. '
            'Otherwise use null.'
        ),
        type='boolean',
        required=False,
        inference_strategy='paper_llm',
        ortholog_allowed=False,
    ),
)

MTB_DEFAULT_CUSTOM_FIELDS = BUILTIN_OPTIONAL_FIELD_TEMPLATES

# Backward compatibility alias used in older tests/docs.
DEFAULT_ANNOTATION_FIELD_DEFS = REQUIRED_DEFAULT_FIELDS + BUILTIN_OPTIONAL_FIELD_TEMPLATES


def _substitute_description(description, *, species_name, canonical_name):
    return (
        description
        .replace('{species_name}', species_name or 'the organism')
        .replace('{canonical_name}', canonical_name or 'the organism')
    )


def custom_fields_from_mappings(payloads):
    if not payloads:
        return ()
    return tuple(AnnotationFieldDef.from_mapping(item) for item in payloads)


def field_defs_from_mappings(payloads):
    """Legacy alias: treat payload as custom fields only."""
    return custom_fields_from_mappings(payloads)


def validate_custom_field(field_def):
    if field_def.key in RESERVED_FIELD_KEYS:
        raise ValueError(f'field key {field_def.key!r} is reserved')
    if field_def.key in {item.key for item in REQUIRED_DEFAULT_FIELDS}:
        raise ValueError(f'field key {field_def.key!r} is a required default and cannot be custom')
    if not FIELD_KEY_PATTERN.fullmatch(field_def.key):
        raise ValueError(f'invalid field key {field_def.key!r}')
    if field_def.type not in VALID_FIELD_TYPES:
        raise ValueError(f'invalid field type {field_def.type!r} for {field_def.key!r}')
    if field_def.inference_strategy not in VALID_INFERENCE_STRATEGIES:
        raise ValueError(
            f'invalid inference_strategy {field_def.inference_strategy!r} for {field_def.key!r}'
        )


def validate_custom_fields(custom_fields):
    seen = set()
    for field_def in custom_fields:
        validate_custom_field(field_def)
        if field_def.key in seen:
            raise ValueError(f'duplicate custom field key {field_def.key!r}')
        seen.add(field_def.key)


def apply_ortholog_policy(fields, kegg_organism_code):
    """Force ortholog_allowed=False when no KEGG code is configured."""
    if kegg_organism_code:
        return fields
    return tuple(
        AnnotationFieldDef(
            key=field_def.key,
            label=field_def.label,
            description=field_def.description,
            type=field_def.type,
            required=field_def.required,
            inference_strategy=field_def.inference_strategy,
            ortholog_allowed=False,
        )
        for field_def in fields
    )


def default_field_ortholog_from_mapping(payload):
    raw = payload.get('default_field_ortholog') or {}
    if not isinstance(raw, dict):
        raise ValueError('default_field_ortholog must be an object')
    allowed_keys = {item.key for item in REQUIRED_DEFAULT_FIELDS}
    result = {}
    for key, value in raw.items():
        if key not in allowed_keys:
            raise ValueError(f'default_field_ortholog key {key!r} is not a default field')
        result[key] = bool(value)
    return result


def _default_fields_for_profile(profile):
    override_map = {}
    raw_settings = getattr(profile, 'default_field_ortholog', None)
    if isinstance(raw_settings, dict):
        override_map = raw_settings
    elif raw_settings:
        override_map = dict(raw_settings)
    merged = []
    for field_def in REQUIRED_DEFAULT_FIELDS:
        ortholog_allowed = override_map.get(field_def.key, field_def.ortholog_allowed)
        merged.append(
            AnnotationFieldDef(
                key=field_def.key,
                label=field_def.label,
                description=field_def.description,
                type=field_def.type,
                required=field_def.required,
                inference_strategy=field_def.inference_strategy,
                ortholog_allowed=ortholog_allowed,
            )
        )
    return tuple(merged)


def resolve_effective_fields(profile):
    custom = profile.custom_fields if hasattr(profile, 'custom_fields') else ()
    if not custom and profile.annotation_fields:
        # Legacy profiles stored all fields in annotation_fields; split defaults from custom.
        default_keys = {item.key for item in REQUIRED_DEFAULT_FIELDS}
        custom = tuple(
            field for field in profile.annotation_fields
            if field.key not in default_keys
        )
    validate_custom_fields(custom)
    fields = _default_fields_for_profile(profile) + tuple(custom)
    return apply_ortholog_policy(fields, profile.kegg_organism_code)


def resolve_annotation_field_defs(profile):
    return resolve_effective_fields(profile)


def include_in_llm_schema(field_def):
    if field_def.inference_strategy == 'paper_llm':
        return True
    # Until GO/essentiality workers exist, keep functional_category in LLM output.
    return field_def.key == 'functional_category'


def llm_schema_fields(profile):
    return tuple(
        field_def for field_def in resolve_effective_fields(profile)
        if include_in_llm_schema(field_def)
    )


def field_def_to_schema_property(field_def, *, species_name=None, canonical_name=None):
    description = _substitute_description(
        field_def.description,
        species_name=species_name,
        canonical_name=canonical_name,
    )
    if field_def.type == 'string':
        return {
            'type': ['string', 'null'],
            'description': description,
        }
    if field_def.type == 'boolean':
        return {
            'type': ['boolean', 'null'],
            'description': description,
        }
    if field_def.type == 'array:string':
        return {
            'type': ['array', 'null'],
            'items': {'type': 'string'},
            'description': description,
        }
    raise ValueError(f'unsupported field type {field_def.type!r}')


def format_fields_for_prompt(fields, *, species_name=None, canonical_name=None):
    lines = []
    for field_def in fields:
        description = _substitute_description(
            field_def.description,
            species_name=species_name,
            canonical_name=canonical_name,
        )
        lines.append(f'- {field_def.key} ({field_def.label}): {description}')
    return '\n'.join(lines)


def format_field_keys_for_prompt(fields):
    return ', '.join(field_def.key for field_def in fields)


def template_by_key(key):
    for template in BUILTIN_OPTIONAL_FIELD_TEMPLATES:
        if template.key == key:
            return template
    return None
