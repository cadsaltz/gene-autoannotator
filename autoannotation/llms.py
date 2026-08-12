import hashlib
import json
import logging
import os
import re
import time

import ollama

from . import field_defs
from . import organisms
from . import utils

# Prompt/schema construction and Ollama response caching for annotation models.
# The rest of the pipeline depends on this module applying a consistent JSON
# shape and null/placeholder policy before responses move downstream.
logging.basicConfig(format='%(asctime)s %(levelname).1s | %(message)s')
log = logging.getLogger(__name__)
log.setLevel(logging.DEBUG)

BIOLOGY_FIELDS = (
    'function',
    'functional_category',
    'drug_susc_impact',
    'infection_impact',
    'essential_in_vitro',
    'essential_in_vivo',
)

# Treat these as absence-of-evidence markers across model outputs. This is a
# normalization policy, not a biological claim about the gene.
UNKNOWN_STRINGS = frozenset({
    '',
    'unknown',
    'missing',
    'n/a',
    'na',
    'not available',
    'insufficient',
    'insufficient evidence',
    'not stated',
    'not reported',
    'null',
    'none',
})

SECTION_HINTS = {
    'abstract': (
        'This excerpt is an abstract. Prioritize mechanism and functional category when '
        'explicitly stated. Do not infer essentiality or drug/infection impacts unless '
        'this text clearly reports them.'
    ),
    'results': (
        'This excerpt is from results. Prioritize experimental essentiality, drug '
        'susceptibility phenotypes, and measured infection phenotypes when explicitly '
        'reported.'
    ),
    'discussion': (
        'This excerpt is from discussion. Prioritize infection impact and mechanistic '
        'interpretation when explicitly stated; do not treat speculation as established fact.'
    ),
}


def is_unknown_value(value):
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip().lower() in UNKNOWN_STRINGS
    if isinstance(value, list):
        return len(value) == 0
    return False


def normalize_annotation_fields(
    parsed, *, require_biology_keys=False, organism_profile=None, field_defs_profile=None,
):
    """Map empty or placeholder values to JSON null while preserving supplied identity."""
    normalized = {
        'gene_id': parsed.get('gene_id') or parsed.get('rv_id'),
        'name': parsed.get('name'),
    }
    if 'rv_id' in parsed:
        normalized['rv_id'] = parsed.get('rv_id')
    elif (
        organism_profile is not None
        and organism_profile.profile_id == 'mtb-h37rv'
        and normalized['gene_id']
    ):
        normalized['rv_id'] = normalized['gene_id']

    schema_profile = field_defs_profile or organism_profile
    if schema_profile is not None:
        biology_field_defs = field_defs.resolve_effective_fields(schema_profile)
    else:
        biology_field_defs = tuple(
            field_defs.AnnotationFieldDef(
                key=key,
                label=key,
                description='',
                type='string' if key != 'functional_category' else 'array:string',
                required=True,
                inference_strategy='paper_llm',
                ortholog_allowed=False,
            )
            for key in BIOLOGY_FIELDS
        )

    for field_def in biology_field_defs:
        field = field_def.key
        if field not in parsed and not require_biology_keys:
            continue
        value = parsed.get(field)
        if is_unknown_value(value):
            normalized[field] = None
        elif field_def.type == 'array:string' and isinstance(value, list):
            categories = [item for item in value if item and str(item).strip()]
            normalized[field] = categories if categories else None
        else:
            normalized[field] = value
    if 'annotation_notes' in parsed:
        notes = parsed.get('annotation_notes')
        normalized['annotation_notes'] = None if is_unknown_value(notes) else notes
    return normalized


def _response_value(response, key, default=None):
    if isinstance(response, dict):
        return response.get(key, default)
    if hasattr(response, key):
        return getattr(response, key)
    try:
        return response[key]
    except Exception:
        return default


def _duration_from_nanoseconds(value):
    if value is None:
        return None
    return value / 1_000_000_000


def _ollama_keep_alive():
    """Unload policy for Ollama models after each API call.

    Default ``0`` unloads the model immediately so only one model tends to stay
    in RAM between pipeline steps. Set ``AUTOANNOTATION_OLLAMA_KEEP_ALIVE=-1``
    (or ``forever``) to never unload; ``5m`` keeps models warm for five minutes.
    """
    from worker.ollama_keep_alive import parse_ollama_keep_alive

    raw = os.getenv('AUTOANNOTATION_OLLAMA_KEEP_ALIVE', '0')
    parsed = parse_ollama_keep_alive(raw)
    if parsed is None:
        return 0
    return parsed


def chat_response_content(response, *, role: str, model: str) -> str:
    try:
        content = response['message']['content']
    except (KeyError, TypeError) as exc:
        raise RuntimeError(
            f'Ollama {role} response missing message content (model {model})'
        ) from exc
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError(f'Ollama {role} returned empty content (model {model})')
    return content


def parse_response_json(text: str, *, role: str, model: str) -> dict:
    if not isinstance(text, str) or not text.strip():
        raise RuntimeError(f'Cannot parse empty JSON for Ollama {role} (model {model})')
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f'Invalid JSON from Ollama {role} (model {model}): {exc}'
        ) from exc
    if not isinstance(payload, dict):
        raise RuntimeError(
            f'Expected JSON object from Ollama {role} (model {model}), got {type(payload).__name__}'
        )
    return payload


def _router_client():
    url = os.getenv('OLLAMA_ROUTER_URL')
    if not url:
        return None
    from worker.router.client import RouterClient
    return RouterClient(url)


def _router_chat_error_detail(exc) -> str:
    import httpx

    if not isinstance(exc, httpx.HTTPStatusError):
        return str(exc)
    try:
        body = exc.response.json()
        if isinstance(body, dict) and body.get('error'):
            return str(body['error'])
    except Exception:
        pass
    if exc.response is not None:
        return exc.response.text.strip() or str(exc)
    return str(exc)


def ollama_chat(
    *,
    model: str,
    messages,
    json_schema=None,
    role: str = 'inference',
    job_id: str | None = None,
):
    job_id = job_id or os.getenv('ANNOTATION_JOB_ID')
    router = _router_client()
    if router is not None:
        chat_kwargs = {
            'model': model,
            'messages': messages,
            'role': role,
            'job_id': job_id,
            'keep_alive': _ollama_keep_alive(),
        }
        if json_schema is not None:
            chat_kwargs['format'] = json_schema
        try:
            return router.chat(**chat_kwargs)
        except Exception as exc:
            import httpx

            if isinstance(exc, httpx.HTTPStatusError):
                detail = _router_chat_error_detail(exc)
                raise RuntimeError(
                    f'Router {role} request failed ({exc.response.status_code}): {detail}'
                ) from exc
            if isinstance(exc, httpx.RequestError):
                detail = str(exc)
                if 'timed out' in detail.lower() or exc.__class__.__name__ == 'ReadTimeout':
                    detail += (
                        '; unset OLLAMA_CHAT_TIMEOUT_SEC and OLLAMA_ROUTER_READ_TIMEOUT_SEC '
                        'for unlimited waits, or raise the limits'
                    )
                raise RuntimeError(f'Router {role} request failed: {detail}') from exc
            raise
    kwargs = {
        'model': model,
        'messages': messages,
        'options': {'temperature': 0},
        'keep_alive': _ollama_keep_alive(),
    }
    if json_schema is not None:
        kwargs['format'] = json_schema
    return ollama.chat(**kwargs)


def _nullable_string(description):
    return {
        'type': ['string', 'null'],
        'description': description + ' Use null when the source text does not support this field.',
    }


def _nullable_bool(description):
    return {
        'type': ['boolean', 'null'],
        'description': (
            description
            + ' Use null when the source text does not report experimental evidence for this field.'
        ),
    }


def _biology_properties(organism_label='the organism'):
    return {
        'function': _nullable_string(
            'What the gene product does for the cell (one or two concise sentences).'
        ),
        'functional_category': {
            'type': ['array', 'null'],
            'items': {'type': 'string'},
            'description': (
                'One or more general cellular functions (e.g., cell wall, respiration, '
                'virulence, DNA replication/repair). Use null if not supported.'
            ),
        },
        'drug_susc_impact': _nullable_string(
            f'Impact on {organism_label} drug susceptibility (one or two concise sentences).'
        ),
        'infection_impact': _nullable_string(
            f'Impact on {organism_label} infection (one or two concise sentences).'
        ),
        'essential_in_vitro': _nullable_bool(
            f'Whether the gene is essential for {organism_label} survival in vitro.'
        ),
        'essential_in_vivo': _nullable_bool(
            f'Whether the gene is essential for {organism_label} survival in vivo.'
        ),
    }


def _identity_properties(organism_profile=None, *, allow_missing_locus=False):
    gene_id_type = ['string', 'null'] if allow_missing_locus else 'string'
    locus_description = 'The gene locus identifier as supplied for this annotation.'
    if allow_missing_locus:
        locus_description += ' Use null when no locus was supplied or resolved.'
    elif organism_profile is not None:
        locus_description = (
            f'The gene locus identifier for {organism_profile.canonical_name}; '
            f'must match this profile regex: {organism_profile.locus_regex}'
        )
    return {
        'gene_id': {
            'type': gene_id_type,
            'description': locus_description,
        },
        'name': {
            'type': 'string',
            'description': (
                'The abbreviated name or symbol of the gene. If no distinct gene name is '
                'available, use the gene_id.'
            ),
        },
    }


def _biology_properties_from_profile(organism_profile=None, field_defs_profile=None):
    if organism_profile is None:
        return _biology_properties('the organism')
    schema_profile = field_defs_profile or organism_profile
    properties = {}
    for field_def in field_defs.llm_schema_fields(schema_profile):
        properties[field_def.key] = field_defs.field_def_to_schema_property(
            field_def,
            species_name=organism_profile.species_name,
            canonical_name=organism_profile.canonical_name,
        )
    return properties


def build_json_schema(
    organism_profile=None,
    *,
    require_biology=False,
    aggregate=False,
    allow_missing_locus=False,
    field_defs_profile=None,
):
    # Ollama's structured output support is used as the first guardrail. The
    # schema is intentionally small because factual support still comes from
    # prompts, section selection, and later curator review.
    required = ['gene_id', 'name']
    schema_profile = field_defs_profile or organism_profile
    llm_fields = (
        field_defs.llm_schema_fields(schema_profile)
        if schema_profile is not None
        else ()
    )
    if require_biology:
        if llm_fields:
            required += [field_def.key for field_def in llm_fields]
        else:
            required += list(BIOLOGY_FIELDS)
    properties = {
        **_identity_properties(organism_profile, allow_missing_locus=allow_missing_locus),
        **_biology_properties_from_profile(organism_profile, field_defs_profile=field_defs_profile),
    }
    if aggregate:
        properties['annotation_notes'] = _nullable_string(
            'Transparency notes for curators: papers analyzed, literature strength, fields left '
            'unknown due to insufficient evidence, limitations, conflicts, and caveats.'
        )
        required.append('annotation_notes')
    return {
        'type': 'object',
        'properties': properties,
        'required': required,
        'additionalProperties': False,
    }


json_schema_section = build_json_schema()
json_schema_default = build_json_schema(require_biology=True)
json_schema_aggregate = build_json_schema(require_biology=True, aggregate=True)

# section field extraction prompt
prompt1_tmpl = '''
Using ONLY the supplied excerpt, return a JSON object for {5} gene {0}
(named {1}).

Section type: {3}
{4}

Rules:
- Always set gene_id and name exactly as supplied above.
- Include every biology field key listed below. Use JSON null for any field this excerpt does
  NOT explicitly support. Do not guess, infer from gene class, or use general organism knowledge.
- Do not use empty strings for unknown fields; use null.
- For essential_in_vitro and essential_in_vivo, use true or false only when this excerpt reports
  direct experimental evidence (e.g., deletion, transposon, CRISPRi). Otherwise use null.
- Prefer null over weak or speculative statements.

Fields:
{6}

Excerpt:
{2}
'''


prompt1_ortholog_tmpl = '''
Using ONLY the supplied excerpt, return a JSON object for {5} gene {0}
(named {1}).

This is an ORTHOLOG inference pass. The excerpt describes the ortholog (source) gene only.
Do NOT state claims as proven for the target gene {6} (named {7}).
Extract candidate values that might transfer to the target gene if supported by orthology,
but output facts about the ortholog gene in the biology fields.

Section type: {3}
{4}

Rules:
- Always set gene_id and name exactly as supplied above (the ortholog identifiers).
- Include every biology field key listed below. Use JSON null for any field this excerpt does
  NOT explicitly support. Do not guess, infer from gene class, or use general organism knowledge.
- Do not use empty strings for unknown fields; use null.
- For essential_in_vitro and essential_in_vivo, use true or false only when this excerpt reports
  direct experimental evidence (e.g., deletion, transposon, CRISPRi). Otherwise use null.
- Prefer null over weak or speculative statements.
- Do not attribute ortholog experimental results to the target gene.

Fields:
{8}

Excerpt:
{2}
'''


def _section_fields_block(organism_profile, field_defs_profile=None):
    if organism_profile is None:
        return (
            'function, functional_category, drug_susc_impact, infection_impact, '
            'essential_in_vitro, essential_in_vivo'
        )
    schema_profile = field_defs_profile or organism_profile
    llm_fields = field_defs.llm_schema_fields(schema_profile)
    return field_defs.format_fields_for_prompt(
        llm_fields,
        species_name=organism_profile.species_name,
        canonical_name=organism_profile.canonical_name,
    )


def build_section_prompt(
    gene, name, text, *, section_type, organism_profile=None,
    evidence_mode='target', ortholog_context=None, field_defs_profile=None,
):
    organism_label = (
        organism_profile.canonical_name
        if organism_profile is not None
        else 'the submitted organism'
    )
    gene_label = gene if gene else 'with no supplied or resolved locus identifier'
    name_label = name if name else gene_label
    missing_locus_rule = ''
    if gene is None:
        missing_locus_rule = (
            '\n- No locus identifier was supplied or resolved. Do not invent a locus '
            'identifier; set gene_id to null.'
        )
    fields_block = _section_fields_block(organism_profile, field_defs_profile=field_defs_profile)
    base_type = section_type.split("#", 1)[0]
    hint = SECTION_HINTS.get(base_type, "")
    if evidence_mode == 'ortholog':
        target_gene = (ortholog_context or {}).get('target_gene_id') or 'the target gene'
        target_name = (ortholog_context or {}).get('target_gene_name') or target_gene
        return prompt1_ortholog_tmpl.format(
            gene_label,
            name_label,
            text,
            section_type,
            hint,
            organism_label,
            target_gene,
            target_name,
            fields_block,
        ) + missing_locus_rule
    return prompt1_tmpl.format(
        gene_label,
        name_label,
        text,
        section_type,
        hint,
        organism_label,
        fields_block,
    ) + missing_locus_rule


BATCH_CONSENSUS_PROMPT = '''
You merge annotation candidate values from different extractor models for the same paper section.

Candidate objects (same section, different extractor models):
{candidates_json}

Merge ONLY these fields: {field_list}

Return JSON with exactly those keys. Use null for any field you cannot reconcile from the candidates.

Rules:
- Reconcile only from the candidate values provided. You do not have access to the source text.
- You may combine overlapping meaning from multiple candidates for the same field using concise wording.
- Do not add facts not present in any candidate.
- If candidates describe incompatible biology for a field, return null for that field.
- Do NOT choose one candidate over others when they conflict — return null instead.
- For list fields, include only category labels that appear in multiple candidates or clearly overlap in meaning.
- Prefer concise phrasing drawn from the candidates.
'''


def _batch_consensus_schema(unresolved_fields, field_defs_profile=None, organism_profile=None):
    properties = {}
    profile = field_defs_profile or organism_profile
    type_by_key = {}
    if profile is not None:
        for field_def in field_defs.llm_schema_fields(profile):
            type_by_key[field_def.key] = field_def.type
    for field_key in unresolved_fields:
        field_type = type_by_key.get(field_key, 'string')
        if field_type == 'array:string':
            properties[field_key] = {'type': ['array', 'null'], 'items': {'type': 'string'}}
        elif field_type == 'boolean':
            properties[field_key] = {'type': ['boolean', 'null']}
        else:
            properties[field_key] = {'type': ['string', 'null']}
    return {
        'type': 'object',
        'properties': properties,
        'required': unresolved_fields,
        'additionalProperties': False,
    }

# json aggregation prompt
prompt3_prefix = '''
The following JSON objects describe the same gene from different paper sections. Each object uses
null for fields that section did not support. Objects are labeled with PMID and literature
relevance score (higher = more relevant to this gene).

Aggregate into one final annotation:
- For each field, synthesize only from non-null contributions. Prefer higher-relevance sources when
  harmonizing details.
- If no object supports a field, output null for that field (not empty string).
- If objects conflict, output null for that field and describe the conflict in annotation_notes.
- For booleans, require consistent experimental support; do not infer essentiality without evidence.
- Cite PMIDs inline for supported prose fields, e.g. "detail (PMID 12345)".

Fill annotation_notes using the literature-selection context when provided. State how many papers
were analyzed, literature strength, which annotation fields remain unknown (null) due to
insufficient evidence, limitations, and conflicts. Do not invent paper counts or PMIDs.

Supplied section objects:
'''

prompt3_ortholog_prefix = '''
The following JSON objects describe the same ORTHOLOG (source) gene from different paper sections.
This is an ortholog inference pass for a different target gene. Each object uses null for fields
that section did not support. Objects are labeled with PMID and literature relevance score.

Aggregate into one ortholog annotation with candidate values for possible transfer:
- For each field, synthesize only from non-null contributions about the ORTHOLOG gene.
- Do NOT state that experimental results apply to the target gene.
- If no object supports a field, output null for that field (not empty string).
- If objects conflict, output null for that field and describe the conflict in annotation_notes.
- For booleans, require consistent experimental support for the ortholog; do not infer without evidence.
- Cite PMIDs inline for supported prose fields, e.g. "detail (PMID 12345)".

Fill annotation_notes explaining this is ortholog-scoped evidence from {0} (target: {1}),
how many ortholog papers were analyzed, literature strength, unknown fields, and that curator
review is required before transferring values to the target gene.

Supplied section objects:
'''


class LlmHandler:
    @staticmethod
    def json_regex_filter(
        gene_json, rv_ptrn='[Rr]v[0-9]{4}[ABc]?',
        name_ptrn='([a-z]{3}[a-zA-Z0-9.]*)|([PE_GRS]{2,7}[0-9A]{1,3})',
        organism_profile=None, expected_gene=None, relaxed_name=False,
    ):
        # This is only a shape/profile filter for model outputs. It rejects
        # wrong-locus or malformed JSON before aggregation but does not check
        # whether the biological statements are true.
        locus_ptrn = organism_profile.locus_regex if organism_profile is not None else rv_ptrn
        has_locus_regex = bool(locus_ptrn)
        if organism_profile is not None:
            name_ptrn = rf'[\w.\-:/]+|{locus_ptrn}'
        else:
            name_ptrn += '|' + locus_ptrn
        try:
            gene_info = json.loads(gene_json)
            gene_id = gene_info.get('gene_id')
            if gene_id is None:
                gene_id = gene_info.get('rv_id')
            if gene_id is None:
                if expected_gene is not None:
                    return False
            else:
                if not isinstance(gene_id, str):
                    return False
                if expected_gene is not None:
                    # Ortholog / explicit-identity passes: gene_id must match the
                    # supplied identifier. Do not also require organism locus_regex —
                    # KEGG SSDB IDs (e.g. MO_*) can differ from annotation-table
                    # schemes (e.g. RJtmp_*).
                    if gene_id != expected_gene:
                        return False
                else:
                    if not gene_id:
                        return False
                    if has_locus_regex and not re.fullmatch(locus_ptrn, gene_id):
                        return False
            name = gene_info.get('name', '')
            if relaxed_name:
                if not isinstance(name, str) or not name.strip():
                    return False
            elif not re.fullmatch(name_ptrn, name):
                return False
            return True
        except (json.JSONDecodeError, TypeError):
            return False

    @staticmethod
    def normalize_response_json(
        gene_json, *, require_biology_keys=False, organism_profile=None, field_defs_profile=None,
        model: str = 'unknown',
        role: str = 'response',
    ):
        parsed = parse_response_json(gene_json, role=role, model=model)
        normalized = normalize_annotation_fields(
            parsed,
            require_biology_keys=require_biology_keys,
            organism_profile=organism_profile,
            field_defs_profile=field_defs_profile,
        )
        return json.dumps(normalized)

    def __init__(self, cache_dir='./.cache'):
        self.cache_dir = cache_dir
        self.usage_records = []

    def _usage_from_response(self, response, duration_sec):
        input_tokens = _response_value(response, 'prompt_eval_count')
        output_tokens = _response_value(response, 'eval_count')
        total_tokens = None
        if input_tokens is not None and output_tokens is not None:
            total_tokens = input_tokens + output_tokens
        return {
            'input_tokens': input_tokens,
            'output_tokens': output_tokens,
            'total_tokens': total_tokens,
            'total_duration_sec': _duration_from_nanoseconds(
                _response_value(response, 'total_duration')
            ) or duration_sec,
            'load_duration_sec': _duration_from_nanoseconds(
                _response_value(response, 'load_duration')
            ),
            'prompt_eval_duration_sec': _duration_from_nanoseconds(
                _response_value(response, 'prompt_eval_duration')
            ),
            'eval_duration_sec': _duration_from_nanoseconds(
                _response_value(response, 'eval_duration')
            ),
        }

    def _record_usage(self, role, model, duration_sec, *, cache_hit=False, usage=None):
        usage = usage or {}
        input_tokens = usage.get('input_tokens')
        output_tokens = usage.get('output_tokens')
        total_tokens = usage.get('total_tokens')
        if total_tokens is None and input_tokens is not None and output_tokens is not None:
            total_tokens = input_tokens + output_tokens
        record = {
            'role': role,
            'model': model,
            'cache_hit': cache_hit,
            'usage_available': input_tokens is not None and output_tokens is not None,
            'input_tokens': input_tokens,
            'output_tokens': output_tokens,
            'total_tokens': total_tokens,
            'duration_sec': duration_sec,
            'total_duration_sec': usage.get('total_duration_sec'),
            'load_duration_sec': usage.get('load_duration_sec'),
            'prompt_eval_duration_sec': usage.get('prompt_eval_duration_sec'),
            'eval_duration_sec': usage.get('eval_duration_sec'),
        }
        self.usage_records.append(record)
        return record

    @staticmethod
    def _empty_usage_group():
        return {
            'calls': 0,
            'cache_hits': 0,
            'known_input_tokens': 0,
            'known_output_tokens': 0,
            'known_total_tokens': 0,
            'usage_records_with_missing_tokens': 0,
        }

    @classmethod
    def _add_usage_to_group(cls, group, record):
        group['calls'] += 1
        if record.get('cache_hit'):
            group['cache_hits'] += 1
        if record.get('usage_available'):
            group['known_input_tokens'] += record.get('input_tokens') or 0
            group['known_output_tokens'] += record.get('output_tokens') or 0
            group['known_total_tokens'] += record.get('total_tokens') or 0
        else:
            group['usage_records_with_missing_tokens'] += 1

    def summarize_usage(self):
        summary = self._empty_usage_group()
        by_role = {}
        by_model = {}
        for record in self.usage_records:
            self._add_usage_to_group(summary, record)
            role = record.get('role') or 'unknown'
            model = record.get('model') or 'unknown'
            role_group = by_role.setdefault(role, self._empty_usage_group())
            model_group = by_model.setdefault(model, self._empty_usage_group())
            self._add_usage_to_group(role_group, record)
            self._add_usage_to_group(model_group, record)
        summary['by_role'] = by_role
        summary['by_model'] = by_model
        return summary

    def get_llm_aggregate_json(
        self, json_responses, pmids, model='gemma3:12b',
        json_schema=None, retry=True, literature_context=None,
        relevance_scores=None, organism_profile=None, allow_missing_locus=False,
        evidence_mode='target', ortholog_context=None, field_defs_profile=None,
    ):
        json_responses = list(json_responses)
        pmids = list(pmids)
        json_schema = json_schema or build_json_schema(
            organism_profile, require_biology=True, aggregate=True,
            allow_missing_locus=allow_missing_locus,
            field_defs_profile=field_defs_profile,
        )
        if evidence_mode == 'ortholog':
            context = ortholog_context or {}
            ortholog_label = context.get('ortholog_gene_id') or 'the ortholog gene'
            target_label = context.get('target_gene_id') or 'the target gene'
            prompt = prompt3_ortholog_prefix.format(ortholog_label, target_label)
        else:
            prompt = prompt3_prefix
        if literature_context:
            prompt += f'\n\n{literature_context}\n'
        if relevance_scores is None:
            relevance_scores = [None] * len(json_responses)
        for pmid, json_response, relevance in zip(pmids, json_responses, relevance_scores):
            # Normalize each section before embedding it in the aggregate
            # prompt so the final model sees a consistent null policy.
            normalized = self.normalize_response_json(
                json_response,
                organism_profile=organism_profile,
                field_defs_profile=field_defs_profile,
            )
            relevance_label = (
                f'{relevance:.3f}' if relevance is not None else 'not available'
            )
            prompt += f'\n\nPMID {pmid} (relevance {relevance_label}): {normalized}'

        cached_response, cached_dur = self._read_cache(model, prompt, json_schema)
        if cached_response is not None:
            log.debug((
                f'Returning cached section-aggregation response ({len(cached_response)} chars)'
            ))
            self._record_usage(
                'gene_aggregation', model, cached_dur, cache_hit=True,
                usage=self._read_cache_usage(model, prompt, json_schema),
            )
            return self.normalize_response_json(
                cached_response,
                require_biology_keys=True,
                organism_profile=organism_profile,
                field_defs_profile=field_defs_profile,
                model=model,
                role='gene_aggregation',
            ), cached_dur

        log.debug((
            f'Submitting section-aggregation job ({len(json_responses)} blurbs; total '
            f'{len(prompt)} chars) to LLM (model {model})'
        ))
        try:
            response = ollama_chat(
                model=model,
                messages=[
                    {
                        'role': 'user',
                        'content': prompt,
                    },
                ],
                json_schema=json_schema,
                role='gene_aggregation',
            )
            response_text = chat_response_content(
                response, role='gene_aggregation', model=model,
            )
            duration_sec = response['total_duration'] / 1_000_000_000
            log.debug(
                f'Got response ({len(response_text)} chars) back from {model} in ' + \
                    utils.seconds_to_str(duration_sec)
            )
            response_text = self.normalize_response_json(
                response_text,
                require_biology_keys=True,
                organism_profile=organism_profile,
                field_defs_profile=field_defs_profile,
                model=model,
                role='gene_aggregation',
            )
            usage = self._usage_from_response(response, duration_sec)
            self._record_usage('gene_aggregation', model, duration_sec, usage=usage)
            self._write_cache(model, prompt, json_schema, response_text, duration_sec, usage)
        except (KeyError, RuntimeError) as exc:
            if retry:
                return self.get_llm_aggregate_json(
                    json_responses, pmids, model=model, json_schema=json_schema,
                    retry=False, literature_context=literature_context,
                    relevance_scores=relevance_scores, organism_profile=organism_profile,
                    allow_missing_locus=allow_missing_locus,
                    evidence_mode=evidence_mode, ortholog_context=ortholog_context,
                    field_defs_profile=field_defs_profile,
                )
            raise RuntimeError(f'Failed to get response back from {model}') from exc
        return response_text, duration_sec

    def _ollama_batch_consensus_merge(
        self,
        candidates,
        unresolved_fields,
        *,
        model,
        organism_profile=None,
        field_defs_profile=None,
    ):
        candidate_payload = [
            {field_key: candidate.get(field_key) for field_key in unresolved_fields}
            for candidate in candidates
        ]
        prompt = BATCH_CONSENSUS_PROMPT.format(
            candidates_json=json.dumps(candidate_payload, indent=2),
            field_list=', '.join(unresolved_fields),
        )
        schema = _batch_consensus_schema(
            unresolved_fields,
            field_defs_profile=field_defs_profile,
            organism_profile=organism_profile,
        )
        response = ollama_chat(
            model=model,
            messages=[{'role': 'user', 'content': prompt}],
            json_schema=schema,
            role='section_consensus',
        )
        payload = parse_response_json(
            chat_response_content(response, role='section_consensus', model=model),
            role='section_consensus',
            model=model,
        )
        duration_sec = response['total_duration'] / 1_000_000_000
        return (
            {field_key: payload.get(field_key) for field_key in unresolved_fields},
            duration_sec,
        )

    def _null_consensus_batch(self, unresolved_fields):
        return {field_key: None for field_key in unresolved_fields}

    def _load_cached_json(self, model, prompt, json_schema, *, role: str):
        cached_response, cached_dur = self._read_cache(model, prompt, json_schema)
        if cached_response is None:
            return None, cached_dur
        try:
            return (
                parse_response_json(cached_response, role=role, model=model),
                cached_dur,
            )
        except RuntimeError as exc:
            log.warning('Ignoring invalid cached %s for model %s: %s', role, model, exc)
            self._invalidate_cache(model, prompt, json_schema)
            return None, cached_dur

    def _run_consensus_batch_merge(
        self,
        normalized,
        unresolved_fields,
        *,
        model,
        organism_profile=None,
        field_defs_profile=None,
        retry: bool = True,
    ):
        for attempt in range(2 if retry else 1):
            try:
                return self._ollama_batch_consensus_merge(
                    normalized,
                    unresolved_fields,
                    model=model,
                    organism_profile=organism_profile,
                    field_defs_profile=field_defs_profile,
                )
            except RuntimeError as exc:
                if attempt == 0 and retry:
                    log.warning(
                        'Consensus batch merge failed for model %s (attempt 1), retrying: %s',
                        model, exc,
                    )
                    continue
                log.warning(
                    'Consensus batch merge failed for model %s; nulling fields %s: %s',
                    model, unresolved_fields, exc,
                )
                return self._null_consensus_batch(unresolved_fields), 0.0
        return self._null_consensus_batch(unresolved_fields), 0.0

    def get_llm_consensus_json(
        self,
        candidates,
        *,
        excerpt=None,
        expected_gene_id=None,
        expected_name=None,
        model='qwen3:8b',
        json_schema=None,
        retry=True,
        section_type='unknown',
        organism_profile=None,
        allow_missing_locus=False,
        field_defs_profile=None,
    ):
        from . import consensus

        if len(candidates) < 2:
            raise ValueError('consensus requires at least two candidate JSON objects')

        organism_profile = organism_profile or organisms.resolve_profile('mtb-h37rv')
        json_schema = json_schema or build_json_schema(
            organism_profile,
            allow_missing_locus=allow_missing_locus,
            field_defs_profile=field_defs_profile,
        )
        fields = consensus.field_specs_from_profile(
            field_defs_profile=field_defs_profile,
            organism_profile=organism_profile,
        )

        def batch_merger(normalized, unresolved_fields):
            cache_prompt = BATCH_CONSENSUS_PROMPT.format(
                candidates_json=json.dumps(
                    [{key: item.get(key) for key in unresolved_fields} for item in normalized],
                    indent=2,
                ),
                field_list=', '.join(unresolved_fields),
            )
            batch_schema = _batch_consensus_schema(
                unresolved_fields,
                field_defs_profile=field_defs_profile,
                organism_profile=organism_profile,
            )
            cached_payload, cached_dur = self._load_cached_json(
                model, cache_prompt, batch_schema, role='section_consensus',
            )
            if cached_payload is not None:
                self._record_usage(
                    'section_consensus', model, cached_dur, cache_hit=True,
                    usage=self._read_cache_usage(model, cache_prompt, batch_schema),
                )
                return cached_payload

            result, duration_sec = self._run_consensus_batch_merge(
                normalized,
                unresolved_fields,
                model=model,
                organism_profile=organism_profile,
                field_defs_profile=field_defs_profile,
                retry=retry,
            )
            usage = None
            self._record_usage('section_consensus', model, duration_sec, usage=usage)
            self._write_cache(
                model, cache_prompt, batch_schema,
                json.dumps(result), duration_sec, usage=usage,
            )
            return result

        start = time.perf_counter()
        try:
            merged, provenance, llm_calls = consensus.hybrid_section_consensus(
                candidates,
                excerpt=excerpt,
                expected_gene_id=expected_gene_id,
                expected_name=expected_name,
                fields=fields,
                organism_profile=organism_profile,
                field_defs_profile=field_defs_profile,
                batch_merger=batch_merger,
            )
        except (KeyError, ValueError) as exc:
            if retry:
                return self.get_llm_consensus_json(
                    candidates,
                    excerpt=excerpt,
                    expected_gene_id=expected_gene_id,
                    expected_name=expected_name,
                    model=model,
                    json_schema=json_schema,
                    retry=False,
                    section_type=section_type,
                    organism_profile=organism_profile,
                    allow_missing_locus=allow_missing_locus,
                    field_defs_profile=field_defs_profile,
                )
            raise RuntimeError(f'Failed to get response back from {model}') from exc
        duration_sec = time.perf_counter() - start
        log.debug(
            'Section consensus (%s): llm_calls=%s provenance=%s',
            section_type, llm_calls, provenance,
        )
        response_text = json.dumps(merged)
        if llm_calls == 0:
            self._record_usage('section_consensus', model, duration_sec, cache_hit=False)
        return self.normalize_response_json(
            response_text,
            organism_profile=organism_profile,
            field_defs_profile=field_defs_profile,
            model=model,
            role='section_consensus',
        ), duration_sec

    def get_llm_gene_info_json(
        self, gene_id, gene_name, info_text, model, json_schema=None,
        retry=True, section_type='unknown', organism_profile=None,
        evidence_mode='target', ortholog_context=None, field_defs_profile=None,
    ):
        organism_profile = organism_profile or organisms.resolve_profile('mtb-h37rv')
        json_schema = json_schema or build_json_schema(
            organism_profile,
            allow_missing_locus=gene_id is None,
            field_defs_profile=field_defs_profile,
        )
        prompt = build_section_prompt(
            gene_id,
            gene_name,
            info_text,
            section_type=section_type,
            organism_profile=organism_profile,
            evidence_mode=evidence_mode,
            ortholog_context=ortholog_context,
            field_defs_profile=field_defs_profile,
        )

        cached_response, cached_dur = self._read_cache(model, prompt, json_schema)
        if cached_response is not None:
            log.debug((
                f'Returning cached section-summary response ({len(cached_response)} chars)'
            ))
            self._record_usage(
                'section_summary', model, cached_dur, cache_hit=True,
                usage=self._read_cache_usage(model, prompt, json_schema),
            )
            return self.normalize_response_json(
                cached_response,
                organism_profile=organism_profile,
                field_defs_profile=field_defs_profile,
                model=model,
                role='section_summary',
            ), cached_dur

        log.debug((
            f'Submitting section-summary job (length {len(prompt)} chars) to LLM (model {model})'
        ))
        try:
            response = ollama_chat(
                model=model,
                messages=[
                    {
                        'role': 'user',
                        'content': prompt,
                    },
                ],
                json_schema=json_schema,
                role='section_summary',
            )
            response_text = chat_response_content(
                response, role='section_summary', model=model,
            )
            duration_sec = response['total_duration'] / 1_000_000_000
            log.debug(
                f'Got response ({len(response_text)} chars) back from {model} in ' + \
                    utils.seconds_to_str(duration_sec)
            )
            response_text = self.normalize_response_json(
                response_text,
                organism_profile=organism_profile,
                field_defs_profile=field_defs_profile,
                model=model,
                role='section_summary',
            )
            usage = self._usage_from_response(response, duration_sec)
            self._record_usage('section_summary', model, duration_sec, usage=usage)
            self._write_cache(model, prompt, json_schema, response_text, duration_sec, usage)
        except (KeyError, RuntimeError) as exc:
            if retry:
                return self.get_llm_gene_info_json(
                    gene_id, gene_name, info_text, model, json_schema=json_schema, retry=False,
                    section_type=section_type, organism_profile=organism_profile,
                    evidence_mode=evidence_mode, ortholog_context=ortholog_context,
                    field_defs_profile=field_defs_profile,
                )
            raise RuntimeError(f'Failed to get response back from {model}') from exc
        return response_text, duration_sec

    def _invalidate_cache(self, model, prompt, json_schema):
        cache_path = self._get_file(model, prompt, json_schema)
        try:
            os.remove(cache_path)
        except OSError:
            pass

    def _get_file(self, model, prompt, json_schema):
        # Cache identity includes the model, full prompt, and JSON schema. That
        # makes prompt/schema edits naturally invalidate stale model responses.
        md5 = hashlib.md5(usedforsecurity=False)
        md5.update(model.encode(encoding='utf8'))
        md5.update(prompt.encode(encoding='utf8'))
        md5.update(json.dumps(json_schema).encode(encoding='utf8'))
        digest = md5.hexdigest()

        return os.path.join(self.cache_dir, 'llm_responses', digest[:3], digest[3:] + '.json')

    def _read_cache(self, model, prompt, json_schema):
        cache_path = self._get_file(model, prompt, json_schema)
        if not os.path.exists(cache_path):
            return None, None
        log.debug(f'Reading cached response for LLM {model}')
        try:
            with open(cache_path) as cache_file:
                cache_obj = json.load(cache_file)
        except (OSError, json.JSONDecodeError) as exc:
            log.warning('Ignoring unreadable cache for model %s at %s: %s', model, cache_path, exc)
            self._invalidate_cache(model, prompt, json_schema)
            return None, None
        response_text = cache_obj.get('response_text')
        if not isinstance(response_text, str) or not response_text.strip():
            log.warning('Ignoring empty cached response for model %s at %s', model, cache_path)
            self._invalidate_cache(model, prompt, json_schema)
            return None, None
        return response_text, cache_obj.get('duration_sec')

    def _read_cache_usage(self, model, prompt, json_schema):
        cache_path = self._get_file(model, prompt, json_schema)
        if not os.path.exists(cache_path):
            return None
        try:
            with open(cache_path) as cache_file:
                cache_obj = json.load(cache_file)
        except (OSError, json.JSONDecodeError):
            return None
        usage = cache_obj.get('usage')
        return usage if isinstance(usage, dict) else None

    def _write_cache(self, model, prompt, json_schema, response_text, duration_sec, usage=None):
        if not isinstance(response_text, str) or not response_text.strip():
            log.warning('Refusing to cache empty response from LLM %s', model)
            return False
        log.debug(f'Caching response from LLM {model}')
        cache_path = self._get_file(model, prompt, json_schema)

        cache_parent = os.path.dirname(cache_path)
        if not os.path.exists(cache_parent):
            os.makedirs(cache_parent, exist_ok=True)

        content = dict(
            duration_sec=duration_sec,
            response_text=response_text,
        )
        if usage is not None:
            content['usage'] = usage
        try:
            with open(cache_path, 'w') as cache_file:
                json.dump(content, cache_file)
            return True
        except Exception:
            log.exception('Error encountered while writing cache file')
