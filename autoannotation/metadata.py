from datetime import datetime, timezone

SELECTION_MODE_LIMITED = 'all_eligible_limited_literature'
SELECTION_MODE_BUDGET = 'cumulative_relevance_budget'

METADATA_FIELDS = ('annotation_metadata', 'annotation_notes')
COMPARISON_IGNORE_FIELDS = frozenset(METADATA_FIELDS)
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


def build_field_coverage(annotation_fields):
    coverage = {}
    biology_fields = (
        'function',
        'functional_category',
        'drug_susc_impact',
        'infection_impact',
        'essential_in_vitro',
        'essential_in_vivo',
    )
    for field in biology_fields:
        value = annotation_fields.get(field)
        if field not in annotation_fields or value is None or value == '' or value == []:
            coverage[field] = 'insufficient_evidence'
        elif field in ('essential_in_vitro', 'essential_in_vivo'):
            coverage[field] = 'supported'
        elif isinstance(value, str) and 'disagreement' in value.lower():
            coverage[field] = 'conflicting'
        else:
            coverage[field] = 'supported'
    return coverage


def build_literature_context_for_notes(
    ranked_records,
    selected_records,
    selection_mode,
    eligible_count,
    cumulative_relevance,
    target_relevance,
    min_papers,
):
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
        'quality_flags': quality_flags,
        'duration_sec': round(duration_sec, 1),
    }


def merge_annotation_output(gene_distillation_json, annotation_metadata, field_coverage=None):
    import json

    parsed = json.loads(gene_distillation_json)
    parsed['annotation_metadata'] = annotation_metadata
    if field_coverage is not None:
        parsed['annotation_metadata']['field_coverage'] = field_coverage
    if 'annotation_notes' not in parsed:
        parsed['annotation_notes'] = None
    return parsed
