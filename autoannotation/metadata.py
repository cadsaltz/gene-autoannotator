from datetime import datetime, timezone
import re

from . import field_defs
from . import llms

# Metadata is the audit trail attached to generated annotations. Keep curator-
# facing confidence, paper selection, and field coverage information here rather
# than blending it into the biological fields themselves.
SELECTION_MODE_LIMITED = 'all_eligible_limited_literature'
SELECTION_MODE_BUDGET = 'cumulative_relevance_budget'

METADATA_FIELDS = ('annotation_metadata', 'annotation_notes')
COMPARISON_IGNORE_FIELDS = frozenset(METADATA_FIELDS)
EMPTY_TARGET_NOTES = (
    'No papers were available for this gene; '
    'no literature-backed target annotation was produced.'
)
EMPTY_ORTHOLOG_NOTES = 'The ortholog pass also found no papers.'
FIELD_PROVENANCE_DIRECT = 'direct'
FIELD_PROVENANCE_ORTHolog_DERIVED = 'ortholog_derived'
FIELD_PROVENANCE_TARGET_PLUS_ORTHOLOG = 'target_plus_ortholog'
DEFAULT_EXCLUDED_WARNINGS = frozenset({
    'excluded_species',
    'missing_target_organism',
    'off_target_organism_dominant',
})


def filter_eligible_records(records, min_score=0.1, excluded_warnings=None):
    excluded_warnings = set(excluded_warnings or DEFAULT_EXCLUDED_WARNINGS)
    eligible = []
    for record in records:
        if record.score < min_score:
            continue
        if excluded_warnings.intersection(record.warnings):
            continue
        eligible.append(record)
    return eligible


def compute_cumulative_relevance(selected_records):
    import math

    cumulative = 0.0
    for selected_rank, record in enumerate(selected_records, start=1):
        cumulative += 2 * record.score / math.log2(selected_rank + 1)
    return cumulative


def build_quality_flags(
    selected_records,
    eligible_count,
    min_papers,
    total_retrieved,
):
    flags = []
    selected_count = len(selected_records)

    if total_retrieved == 0:
        flags.append('no_papers_retrieved')
    if eligible_count == 0:
        flags.append('no_eligible_papers')
    if selected_count == 0:
        flags.append('no_papers_analyzed')
    if eligible_count <= min_papers and eligible_count > 0:
        flags.append('limited_literature')
    if selected_count < min_papers:
        flags.append('below_min_papers_requested')
    if selected_count > 0:
        scores = [record.score for record in selected_records]
        mean_score = sum(scores) / len(scores)
        if mean_score >= 0.7:
            flags.append('strong_literature_support')
        elif mean_score < 0.4:
            flags.append('weak_literature_support')
        low_relevance = sum(score < 0.35 for score in scores)
        if low_relevance > len(scores) / 2:
            flags.append('relied_on_low_relevance_papers')
    return flags


def build_field_coverage(annotation_fields, profile=None):
    coverage = {}
    if profile is not None:
        field_keys = field_defs.resolve_effective_fields(profile)
    else:
        field_keys = tuple(
            field_defs.AnnotationFieldDef(
                key=key,
                label=key,
                description='',
                type='string' if key not in ('functional_category',) else 'array:string',
                required=True,
                inference_strategy='paper_llm',
                ortholog_allowed=False,
            )
            for key in (
                'function',
                'functional_category',
                'drug_susc_impact',
                'infection_impact',
                'essential_in_vitro',
                'essential_in_vivo',
            )
        )
    for field_def in field_keys:
        field = field_def.key
        value = annotation_fields.get(field)
        if field not in annotation_fields or value is None or value == '' or value == []:
            coverage[field] = 'insufficient_evidence'
        elif field_def.type == 'boolean' or field in ('essential_in_vitro', 'essential_in_vivo'):
            coverage[field] = 'supported'
        elif isinstance(value, str) and 'disagreement' in value.lower():
            coverage[field] = 'conflicting'
        else:
            coverage[field] = 'supported'
    return coverage


def empty_annotation_from_metadata(annotation_metadata, *, gene_id, name, profile):
    doc = {
        'gene_id': gene_id,
        'name': name,
        'annotation_notes': EMPTY_TARGET_NOTES,
        'annotation_metadata': dict(annotation_metadata or {}),
    }
    for field_def in field_defs.resolve_effective_fields(profile):
        doc[field_def.key] = None
    doc['annotation_metadata']['field_coverage'] = build_field_coverage(doc, profile=profile)
    return doc


def build_literature_context_for_notes(
    ranked_records,
    selected_records,
    selection_mode,
    eligible_count,
    cumulative_relevance,
    target_relevance,
    min_papers,
):
    # This string is prompt input for annotation_notes, so it should stay factual
    # and derived from ranking metadata. The model may summarize these facts but
    # should not be the source of paper counts or selection statistics.
    total_retrieved = len(ranked_records)
    selected_count = len(selected_records)
    scores = [record.score for record in selected_records]
    mean_selected = sum(scores) / len(scores) if scores else 0.0
    high_relevance_pool = sum(record.score >= 0.75 for record in ranked_records)
    moderate_relevance_pool = sum(0.5 <= record.score < 0.75 for record in ranked_records)

    lines = [
        'Use the following literature-selection context when writing annotation_notes.',
        'Do not invent paper counts or PMIDs beyond what is listed here.',
        f'- Total PMC papers retrieved for this gene: {total_retrieved}',
        f'- Eligible papers after filtering (score and species rules): {eligible_count}',
        f'- Papers selected for analysis: {selected_count}',
        f'- Selection mode: {selection_mode}',
        f'- Cumulative relevance budget: {cumulative_relevance:.3f} (target {target_relevance:.1f}, minimum papers {min_papers})',
        f'- Mean relevance score of selected papers: {mean_selected:.3f}',
        f'- Papers in retrieved set with relevance >= 0.75: {high_relevance_pool}',
        f'- Papers in retrieved set with relevance 0.50-0.74: {moderate_relevance_pool}',
    ]

    if selection_mode == SELECTION_MODE_LIMITED:
        lines.append(
            '- Limited literature: fewer eligible papers than the minimum requested, so '
            'every eligible paper was analyzed.'
        )
    elif high_relevance_pool >= 10 and mean_selected >= 0.7:
        lines.append(
            '- This gene is well studied: many high-relevance papers were available and the '
            'selected set is generally strong.'
        )
    elif mean_selected < 0.4 or 'relied_on_low_relevance_papers' in build_quality_flags(
        selected_records, eligible_count, min_papers, total_retrieved,
    ):
        lines.append(
            '- Several lower-relevance papers were included to meet the analysis budget; '
            'treat conclusions cautiously.'
        )

    lines.append('- Selected papers (PMC ID, relevance score, title):')
    for record in selected_records:
        title = record.title or '[title unavailable]'
        lines.append(f'  - PMC{record.pmc_id} ({record.score:.3f}): {title}')

    lines.append(
        'In annotation_notes, briefly explain how many papers were analyzed, whether the '
        'literature base was strong or weak, which annotation fields could not be populated '
        '(left as null due to insufficient evidence), notable limitations, and any conflicts. '
        'Write for a curator reviewing this annotation.'
    )
    return '\n'.join(lines)


def build_annotation_metadata(
    gene,
    gene_name,
    ranked_records,
    selected_records,
    analyzed_pmc_ids,
    pmids_analyzed,
    sections_analyzed,
    selection_mode,
    eligible_count,
    cumulative_relevance,
    target_relevance,
    min_papers,
    max_papers,
    duration_sec,
    profile_id=None,
    canonical_name=None,
    species_name=None,
    strain=None,
    gene_name_source=None,
    gene_name_source_detail=None,
    gene_name_candidates=None,
    gene_name_confidence=None,
    gene_name_aliases=None,
    gene_name_warnings=None,
    submitted_locus=None,
    submitted_name=None,
    resolved_locus=None,
    resolved_name=None,
    profile_source=None,
    target_warnings=None,
    llm_usage=None,
):
    quality_flags = build_quality_flags(
        selected_records,
        eligible_count,
        min_papers,
        len(ranked_records),
    )
    return {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'gene': gene,
        'gene_name': gene_name,
        'submitted_locus': submitted_locus,
        'submitted_name': submitted_name,
        'resolved_locus': resolved_locus,
        'resolved_name': resolved_name,
        'profile_source': profile_source,
        'target_warnings': list(target_warnings or []),
        'profile_id': profile_id,
        'canonical_name': canonical_name,
        'species_name': species_name,
        'strain': strain,
        'gene_name_source': gene_name_source,
        'gene_name_source_detail': gene_name_source_detail,
        'gene_name_confidence': gene_name_confidence,
        'gene_name_aliases': list(gene_name_aliases or []),
        'gene_name_candidates': list(gene_name_candidates or []),
        'gene_name_warnings': list(gene_name_warnings or []),
        'selection_mode': selection_mode,
        'literature': {
            'total_papers_retrieved': len(ranked_records),
            'papers_eligible': eligible_count,
            'papers_selected': len(selected_records),
            'papers_analyzed': len(analyzed_pmc_ids),
            'sections_analyzed': sections_analyzed,
            'cumulative_relevance': round(cumulative_relevance, 3),
            'target_relevance': target_relevance,
            'min_papers_requested': min_papers,
            'max_papers_allowed': max_papers,
            'mean_selected_relevance': round(
                sum(record.score for record in selected_records) / len(selected_records),
                3,
            ) if selected_records else 0.0,
            'pmc_ids_retrieved': [record.pmc_id for record in ranked_records],
            'pmc_ids_selected': [record.pmc_id for record in selected_records],
            'pmc_ids_analyzed': analyzed_pmc_ids,
            'pmids_analyzed': pmids_analyzed,
            'selected_paper_summaries': [
                {
                    'pmc_id': record.pmc_id,
                    'pmid': record.pmid,
                    'score': record.score,
                    'title': record.title,
                    'year': record.year,
                    'retrieval_sources': record.retrieval_sources,
                    'warnings': record.warnings,
                }
                for record in selected_records
            ],
        },
        'llm_usage': llm_usage or {
            'calls': 0,
            'cache_hits': 0,
            'known_input_tokens': 0,
            'known_output_tokens': 0,
            'known_total_tokens': 0,
            'usage_records_with_missing_tokens': 0,
            'by_role': {},
            'by_model': {},
        },
        'quality_flags': quality_flags,
        'duration_sec': round(duration_sec, 1),
    }


def merge_annotation_output(gene_distillation_json, annotation_metadata, field_coverage=None):
    import json

    # Final persisted annotations keep model-generated biological fields at the
    # top level and attach pipeline-generated metadata underneath
    # annotation_metadata.
    parsed = json.loads(gene_distillation_json)
    parsed['annotation_metadata'] = annotation_metadata
    if field_coverage is not None:
        parsed['annotation_metadata']['field_coverage'] = field_coverage
    if 'annotation_notes' not in parsed:
        parsed['annotation_notes'] = None
    return parsed


def _field_value_missing(value):
    return llms.is_unknown_value(value)


# Locus-like tokens that LLMs hallucinate into the wrong gene's annotations.
_LOCUS_CLAIM_RE = re.compile(
    r'\b(?:'
    r'Rv\d{4}[A-Za-z]?'
    r'|MSMEG_\d+'
    r'|MMAR_\d+'
    r'|BCG_\d+[A-Za-z]?'
    r'|MAB_\d+[A-Za-z]?'
    r'|NCgl\d+'
    r'|MO_\d+'
    r'|RJtmp_\d+'
    r'|b\d{4}'
    r')\b',
    re.IGNORECASE,
)


def text_mentions_other_locus(text, expected_gene_id):
    """True when free text names a different locus than the gene being annotated."""
    if not expected_gene_id or not isinstance(text, str):
        return False
    expected = str(expected_gene_id).strip().lower()
    if not expected:
        return False
    for match in _LOCUS_CLAIM_RE.finditer(text):
        if match.group(0).lower() != expected:
            return True
    return False


def null_out_other_locus_claims(annotation, *, expected_gene_id):
    """Null biology string fields that attribute evidence to a different locus.

    gene_id shape checks only keep identity fields honest; the body text can still
    describe another gene (e.g. infection_impact about Rv0792c while annotating
    Rv1734c). Drop those values so ortholog fallback can fill eligible gaps.
    """
    if not annotation or not expected_gene_id:
        return annotation
    cleaned = dict(annotation)
    for field_def in field_defs.REQUIRED_DEFAULT_FIELDS:
        if field_def.type not in {'string', 'array:string'}:
            continue
        key = field_def.key
        value = cleaned.get(key)
        if isinstance(value, str) and text_mentions_other_locus(value, expected_gene_id):
            cleaned[key] = None
        elif isinstance(value, list):
            kept = [
                item for item in value
                if not (isinstance(item, str) and text_mentions_other_locus(item, expected_gene_id))
            ]
            if not kept and value:
                cleaned[key] = None
            elif len(kept) != len(value):
                cleaned[key] = kept or None
    # Custom biology fields follow the same rule when present on the annotation.
    for key, value in list(cleaned.items()):
        if key in {'gene_id', 'name', 'rv_id', 'annotation_metadata', 'annotation_notes'}:
            continue
        if key in {field.key for field in field_defs.REQUIRED_DEFAULT_FIELDS}:
            continue
        if isinstance(value, str) and text_mentions_other_locus(value, expected_gene_id):
            cleaned[key] = None
    return cleaned


def find_fields_needing_ortholog(direct_annotation, field_coverage, profile_field_defs):
    from . import field_defs as field_defs_module

    missing = []
    coverage = field_coverage or {}
    for field_def in profile_field_defs:
        if not field_def.ortholog_allowed:
            continue
        if not field_defs_module.include_in_llm_schema(field_def):
            continue
        value = direct_annotation.get(field_def.key)
        coverage_status = coverage.get(field_def.key)
        if _field_value_missing(value) or coverage_status == 'insufficient_evidence':
            missing.append(field_def.key)
    return missing


def fields_eligible_for_ortholog(profile_field_defs):
    """All ortholog-allowed, in-schema fields regardless of whether the target
    filled them (the relevance-budget trigger decides whether the pass runs)."""
    eligible = []
    for field_def in profile_field_defs:
        if not field_def.ortholog_allowed:
            continue
        if not field_defs.include_in_llm_schema(field_def):
            continue
        eligible.append(field_def.key)
    return eligible


def merge_ortholog_evidence(
    direct_annotation,
    ortholog_annotation,
    fields_to_fill,
    ortholog_hit,
    *,
    target_gene_id=None,
    target_gene_name=None,
):
    merged = dict(direct_annotation)
    metadata_block = dict(merged.get('annotation_metadata') or {})
    field_provenance = dict(metadata_block.get('field_provenance') or {})
    review_flags = dict(metadata_block.get('review_flags') or {})
    fields_filled = []

    for field_key in fields_to_fill:
        direct_value = merged.get(field_key)
        if not _field_value_missing(direct_value):
            continue
        ortholog_value = (ortholog_annotation or {}).get(field_key)
        if _field_value_missing(ortholog_value):
            continue
        merged[field_key] = ortholog_value
        field_provenance[field_key] = FIELD_PROVENANCE_ORTHolog_DERIVED
        review_flags[field_key] = True
        fields_filled.append(field_key)

    if fields_filled:
        ortholog_label = (
            f'{ortholog_hit.source_organism_code}:{ortholog_hit.source_gene_id}'
        )
        if ortholog_hit.source_organism_name:
            ortholog_label = (
                f'{ortholog_hit.source_gene_id} ({ortholog_hit.source_organism_name})'
            )
        target_label = target_gene_id or 'target gene'
        if target_gene_name:
            target_label = f'{target_label} ({target_gene_name})'
        note = (
            f'Fields filled from ortholog evidence ({", ".join(fields_filled)}) using '
            f'top KEGG SSDB hit {ortholog_label} (score {ortholog_hit.score}). '
            f'These values describe the ortholog gene, not direct experimental evidence '
            f'for {target_label}; curator review required.'
        )
        existing_notes = merged.get('annotation_notes')
        if existing_notes:
            merged['annotation_notes'] = f'{existing_notes}\n\n{note}'
        else:
            merged['annotation_notes'] = note

    metadata_block['field_provenance'] = field_provenance
    metadata_block['review_flags'] = review_flags
    merged['annotation_metadata'] = metadata_block
    return merged, fields_filled


def merge_ortholog_annotation(
    direct_annotation,
    ortholog_annotation,
    eligible_fields,
    ortholog_hit,
    *,
    target_gene_id=None,
    target_gene_name=None,
):
    """Copy ortholog values into ortholog-allowed target fields that are unknown.

    Simple gap-fill for eligible fields:
    - target unknown, ortholog present -> canonical = ortholog, provenance ortholog_derived
    - both present -> keep target canonical, store ortholog in ortholog_fields
      (target_plus_ortholog)
    - ortholog unknown -> no change
    """
    merged = dict(direct_annotation)
    metadata_block = dict(merged.get('annotation_metadata') or {})
    field_provenance = dict(metadata_block.get('field_provenance') or {})
    review_flags = dict(metadata_block.get('review_flags') or {})
    ortholog_fields = dict(metadata_block.get('ortholog_fields') or {})
    fields_filled = []

    for field_key in eligible_fields:
        ortholog_value = (ortholog_annotation or {}).get(field_key)
        if _field_value_missing(ortholog_value):
            continue
        direct_value = merged.get(field_key)
        if _field_value_missing(direct_value):
            merged[field_key] = ortholog_value
            field_provenance[field_key] = FIELD_PROVENANCE_ORTHolog_DERIVED
        else:
            field_provenance[field_key] = FIELD_PROVENANCE_TARGET_PLUS_ORTHOLOG
        ortholog_fields[field_key] = {
            'value': ortholog_value,
            'source_organism': ortholog_hit.source_organism_name,
            'source_organism_code': ortholog_hit.source_organism_code,
            'source_gene_id': ortholog_hit.source_gene_id,
            'source_gene_name': ortholog_hit.source_gene_name,
            'identity': ortholog_hit.identity,
            'score': ortholog_hit.score,
        }
        review_flags[field_key] = True
        fields_filled.append(field_key)

    if fields_filled:
        ortholog_label = ortholog_hit.source_gene_id
        if ortholog_hit.source_organism_name:
            ortholog_label = f'{ortholog_hit.source_gene_id} ({ortholog_hit.source_organism_name})'
        target_label = target_gene_id or 'target gene'
        if target_gene_name:
            target_label = f'{target_label} ({target_gene_name})'
        note = (
            f'Ortholog evidence added for fields ({", ".join(fields_filled)}) from '
            f'{ortholog_label} (identity {ortholog_hit.identity}, score {ortholog_hit.score}). '
            f'Ortholog-derived values describe the ortholog gene, not direct experimental '
            f'evidence for {target_label}; curator review required.'
        )
        existing_notes = merged.get('annotation_notes')
        merged['annotation_notes'] = f'{existing_notes}\n\n{note}' if existing_notes else note

    metadata_block['field_provenance'] = field_provenance
    metadata_block['review_flags'] = review_flags
    if ortholog_fields:
        metadata_block['ortholog_fields'] = ortholog_fields
    merged['annotation_metadata'] = metadata_block
    return merged, fields_filled


def build_ortholog_pass_metadata(
    *,
    ran,
    skipped_reason=None,
    fields_requested=None,
    fields_filled=None,
    papers_analyzed=None,
    pmids_analyzed=None,
):
    return {
        'ran': ran,
        'skipped_reason': skipped_reason,
        'fields_requested': list(fields_requested or []),
        'fields_filled': list(fields_filled or []),
        'papers_analyzed': list(papers_analyzed or []),
        'pmids_analyzed': list(pmids_analyzed or []),
    }


def attach_ortholog_metadata(annotation, ortholog_hit, ortholog_pass_metadata):
    if annotation is None:
        return None
    metadata_block = dict(annotation.get('annotation_metadata') or {})
    if ortholog_hit is not None:
        metadata_block['ortholog_top_hit'] = ortholog_hit.to_metadata()
    else:
        metadata_block['ortholog_top_hit'] = None
    metadata_block['ortholog_pass'] = ortholog_pass_metadata
    annotation['annotation_metadata'] = metadata_block
    return annotation
