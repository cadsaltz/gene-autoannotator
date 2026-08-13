import json
import logging
import re
import time
from dataclasses import dataclass

import pandas as pd

# Orchestrates the full annotation pipeline. Lower-level modules own organism
# resolution, paper retrieval, model prompting, and metadata construction; this
# function keeps those contracts in one linear flow so CLI and web jobs share
# the same behavior.
from . import field_defs
from . import go_resolution
from . import llms
from . import gene_names
from . import metadata
from . import organisms
from . import orthology
from . import pmc
from . import targets
from . import utils

from .models import MODEL_SUMMARY, MODEL_AGGREGATION, MODEL_CONSENSUS
from .section_chunking import expand_sections, excerpt_max_chars_from_env
from shared.job_progress import JobProgressEvent

logging.basicConfig(format='%(asctime)s %(levelname).1s | %(message)s')
log = logging.getLogger(__name__)
log.setLevel(logging.DEBUG)


@dataclass
class PaperAnnotationPassResult:
    gene_distillation: str | None
    ranked_papers: list
    selection: pmc.PaperSelectionResult
    used_pmc_ids: list
    pmids_analyzed: list
    sections_analyzed: int
    cumulative_relevance: float


def _safe_mapping_component(value):
    component = re.sub(r'[^A-Za-z0-9._-]+', '_', str(value).strip())
    component = re.sub(r'\.+', '.', component).strip('._-')
    return component or 'target'


def _pmc_mapping_cache_key(profile, target):
    identifier = _safe_mapping_component(target.primary_identifier)
    if profile.profile_id == 'mtb-h37rv' and target.resolved_locus:
        return identifier
    profile_component = _safe_mapping_component(profile.profile_id)
    return f'{profile_component}__{identifier}'


def collect_paper_sections(paper_manager, pmc_id):
    """Gather the (label, text) sections available for a paper with no LLM calls.

    Used both to build the section work list and to pre-scan totals for
    progress reporting before any inference happens.
    """
    sections = []
    abstract = paper_manager.get_abstract(pmc_id)
    if abstract is not None:
        sections.append(('abstract', abstract))
    results = paper_manager.get_results(pmc_id)
    if results is not None:
        sections.append(('results', results))
    discussion = paper_manager.get_discussion(pmc_id)
    if discussion is not None and discussion != results:
        sections.append(('discussion', discussion))
    return sections


def _sections_for_extraction(paper_manager, pmc_id, *, max_chars):
    raw_sections = collect_paper_sections(paper_manager, pmc_id)
    from .section_chunking import section_chunking_enabled
    if not section_chunking_enabled():
        return raw_sections
    return expand_sections(raw_sections, max_chars=max_chars)


_PASS_PHASES = {
    'target': {
        'fetching': 'fetching',
        'extracting': 'extracting',
        'aggregating': 'aggregating',
        'go_resolving': 'go_resolving',
    },
    'ortholog': {
        'fetching': 'ortholog_fetching',
        'extracting': 'ortholog_extracting',
        'aggregating': 'ortholog_aggregating',
        'go_resolving': 'ortholog_go_resolving',
    },
}


def _emit_progress(progress_cb, evidence_mode, phase_key, **fields):
    if progress_cb is None:
        return
    pass_name = 'ortholog' if evidence_mode == 'ortholog' else 'target'
    phase = _PASS_PHASES[pass_name][phase_key]
    progress_cb(JobProgressEvent(phase=phase, pass_name=pass_name, **fields))


def _profile_lookup_from_config(profile_config):
    # Any attached profile_config is the job-time snapshot of the profile the
    # coordinator resolved from the local profile store. Always use it when
    # present — do not fall back to code catalog defaults.
    if not profile_config:
        return None

    identifiers = [
        profile_config.get('profile_id'),
        profile_config.get('canonical_name'),
        *(profile_config.get('synonyms') or ()),
    ]
    normalized_identifiers = {
        organisms.normalize_identifier(str(identifier))
        for identifier in identifiers
        if identifier
    }

    def lookup_profile(profile_identifier):
        if profile_identifier is None:
            return None
        normalized_identifier = organisms.normalize_identifier(str(profile_identifier))
        if normalized_identifier in normalized_identifiers:
            return profile_config
        return None

    return lookup_profile


def _resolve_profile_from_catalog(profile_id, *, profile_config=None, ortholog_catalog=None):
    """Resolve a profile id from the job snapshot, then the code catalog."""
    if profile_config and profile_config.get('profile_id') == profile_id:
        return organisms.profile_from_mapping(profile_config)
    for document in ortholog_catalog or ():
        if document.get('profile_id') == profile_id:
            return organisms.profile_from_mapping(document)
    return organisms.resolve_profile(profile_id)


def run_paper_annotation_pass(
    gene,
    name,
    display_gene,
    organism_profile,
    *,
    llm_handler,
    paper_manager,
    cache_key,
    evidence_mode='target',
    ortholog_context=None,
    save_pmc_mapping=True,
    field_defs_profile=None,
    progress_cb=None,
):
    _emit_progress(progress_cb, evidence_mode, 'fetching', sections_done=0, sections_total=None)

    ranked_papers = paper_manager.get_ranked_papers(gene, name)
    pmc_ids = [record.pmc_id for record in ranked_papers]
    if save_pmc_mapping and cache_key is not None:
        paper_manager.save_gene_pmc_ids(cache_key, pmc_ids)

    if len(pmc_ids) < 3:
        log.warning(
            f'Found only {len(pmc_ids)} paper{utils.s_if_plural(pmc_ids)} for gene {display_gene}'
        )

    selection = paper_manager.select_relevance_records(
        ranked_papers,
        target_relevance=pmc.DEFAULT_TARGET_RELEVANCE,
        min_score=pmc.DEFAULT_MIN_SCORE,
        max_rank=pmc.DEFAULT_MAX_RANK,
        min_papers=pmc.DEFAULT_MIN_PAPERS,
        max_papers=pmc.DEFAULT_MAX_PAPERS,
    )
    papers_to_analyze = [record.pmc_id for record in selection.selected_records]
    cumulative_relevance = selection.cumulative_relevance

    if selection.selection_mode == metadata.SELECTION_MODE_LIMITED:
        log.warning(
            f'Limited literature for gene {display_gene}: analyzing all '
            f'{len(papers_to_analyze)} eligible paper{utils.s_if_plural(papers_to_analyze)} '
            f'(fewer than minimum {pmc.DEFAULT_MIN_PAPERS})'
        )

    used = []
    section_distillation_candidates = []
    section_distillations = []
    relevance_by_pmc_id = {record.pmc_id: record for record in ranked_papers}

    # Pre-scan section availability for every selected paper before any LLM
    # call so progress totals are known up front.
    max_chars = excerpt_max_chars_from_env()
    papers_sections = [
        (pmc_id, _sections_for_extraction(paper_manager, pmc_id, max_chars=max_chars))
        for pmc_id in papers_to_analyze
    ]
    sections_total = sum(len(sections) for _, sections in papers_sections)
    sections_done = 0
    _emit_progress(
        progress_cb, evidence_mode, 'extracting',
        sections_done=sections_done, sections_total=sections_total,
    )

    for pmc_id, sections in papers_sections:
        relevance_record = relevance_by_pmc_id.get(pmc_id)
        relevance_score = relevance_record.score if relevance_record is not None else 0.0
        log.info(
            f'Starting {evidence_mode} inference for gene {display_gene} with paper PMC{pmc_id} '
            f'(relevance score {relevance_score:.3f})'
        )
        used.append(pmc_id)

        for label, section in sections:
            section_distillation_candidates_cur = []
            llm_gene = gene
            llm_name = name or display_gene
            for model in MODEL_SUMMARY:
                section_distillation_candidate, duration_sec = llm_handler.get_llm_gene_info_json(
                    llm_gene, llm_name, section, model, section_type=label,
                    organism_profile=organism_profile,
                    evidence_mode=evidence_mode,
                    ortholog_context=ortholog_context,
                    field_defs_profile=field_defs_profile,
                )
                section_distillation_candidates_cur.append(section_distillation_candidate)
                section_distillation_candidates.append((
                    f'PMC{pmc_id}', label, model, llm_gene, llm_name,
                    section_distillation_candidate, duration_sec,
                ))
            section_distillation, duration_sec = llm_handler.get_llm_consensus_json(
                section_distillation_candidates_cur,
                excerpt=section,
                expected_gene_id=gene,
                expected_name=llm_name,
                model=MODEL_CONSENSUS,
                section_type=label,
                organism_profile=organism_profile,
                allow_missing_locus=gene is None,
                field_defs_profile=field_defs_profile,
            )
            section_distillations.append((
                f'PMC{pmc_id}', label, MODEL_CONSENSUS, llm_gene, llm_name,
                section_distillation, duration_sec,
            ))
            sections_done += 1
            _emit_progress(
                progress_cb, evidence_mode, 'extracting',
                sections_done=sections_done, sections_total=sections_total,
            )

    section_distillation_df = pd.DataFrame(
        section_distillations,
        columns=['PmcId', 'SectionType', 'Model', 'Gene', 'GeneName', 'Response', 'LlmDur'],
    )
    if len(section_distillation_df) > 0:
        section_distillation_df.insert(
            1, 'PMID', section_distillation_df['PmcId'].map(paper_manager.get_pmid),
        )

    section_distillation_filtered_df = section_distillation_df.loc[
        section_distillation_df['Response'].map(
            lambda response: llm_handler.json_regex_filter(
                response,
                organism_profile=organism_profile,
                expected_gene=gene,
                relaxed_name=(evidence_mode == 'ortholog'),
            )
        ),
        :
    ] if len(section_distillation_df) > 0 else section_distillation_df

    pmids_analyzed = []
    if len(section_distillation_filtered_df) > 0:
        pmids_analyzed = [
            str(pmid) for pmid in section_distillation_filtered_df['PMID'].dropna().unique()
        ]

    literature_context = metadata.build_literature_context_for_notes(
        ranked_records=ranked_papers,
        selected_records=selection.selected_records,
        selection_mode=selection.selection_mode,
        eligible_count=selection.eligible_count,
        cumulative_relevance=cumulative_relevance,
        target_relevance=pmc.DEFAULT_TARGET_RELEVANCE,
        min_papers=pmc.DEFAULT_MIN_PAPERS,
    )

    gene_distillation = None
    if len(section_distillation_filtered_df) >= 1:
        def _relevance_for_pmc_label(pmc_label):
            pmc_id = str(pmc_label).removeprefix('PMC')
            record = relevance_by_pmc_id.get(pmc_id)
            return record.score if record is not None else None

        relevance_scores = section_distillation_filtered_df['PmcId'].map(_relevance_for_pmc_label)
        _emit_progress(
            progress_cb, evidence_mode, 'aggregating',
            sections_done=sections_done, sections_total=sections_total,
        )
        gene_distillation, _duration_sec = llm_handler.get_llm_aggregate_json(
            section_distillation_filtered_df['Response'],
            section_distillation_filtered_df['PMID'],
            model=MODEL_AGGREGATION,
            literature_context=literature_context,
            relevance_scores=relevance_scores.tolist(),
            organism_profile=organism_profile,
            allow_missing_locus=gene is None,
            evidence_mode=evidence_mode,
            ortholog_context=ortholog_context,
            field_defs_profile=field_defs_profile,
        )

    return PaperAnnotationPassResult(
        gene_distillation=gene_distillation,
        ranked_papers=ranked_papers,
        selection=selection,
        used_pmc_ids=used,
        pmids_analyzed=pmids_analyzed,
        sections_analyzed=len(section_distillation_filtered_df),
        cumulative_relevance=cumulative_relevance,
    )


@dataclass
class OrthologDecision:
    hit: orthology.OrthologHit | None
    skipped_reason: str | None


def _decide_ortholog_action(
    *, allow_ortholog_fallback, ortholog_override, cumulative_relevance,
    kegg_code, gene, cache_dir, profile_config=None, ortholog_catalog=None,
    kegg_locus_regex=None,
):
    """Decide whether/how to run the ortholog fallback. May perform a cache/network
    SSDB lookup on the automatic path.

    ortholog_override modes:
    - profile + locus: manual ortholog hit (bypasses relevance gate and SSDB)
    - profile only: automatic SSDB search restricted to that organism's KEGG code
    - absent: automatic SSDB search across all profiled organisms
    """
    if not allow_ortholog_fallback:
        return OrthologDecision(hit=None, skipped_reason='fallback_disabled_for_job')

    restrict_to_organism_code = None
    if ortholog_override:
        override_profile = _resolve_profile_from_catalog(
            ortholog_override['profile_id'],
            profile_config=profile_config,
            ortholog_catalog=ortholog_catalog,
        )
        override_locus = ortholog_override.get('locus')
        if override_locus:
            hit = orthology.build_manual_ortholog_hit(
                override_profile,
                override_locus,
                name=ortholog_override.get('name'),
            )
            return OrthologDecision(hit=hit, skipped_reason=None)
        restrict_to_organism_code = (
            (override_profile.kegg_organism_code or '').lower() or None
        )
        if not restrict_to_organism_code:
            return OrthologDecision(hit=None, skipped_reason='no_profiled_ortholog')

    if cumulative_relevance >= pmc.DEFAULT_TARGET_RELEVANCE:
        return OrthologDecision(hit=None, skipped_reason='target_relevance_sufficient')

    if not (kegg_code and gene):
        return OrthologDecision(hit=None, skipped_reason='no_ortholog_found')

    kegg_locus = orthology.resolve_kegg_locus(gene, kegg_locus_regex)
    hit = orthology.lookup_best_profiled_ortholog(
        kegg_code,
        kegg_locus,
        cache_dir=cache_dir,
        extra_profiles=ortholog_catalog,
        restrict_to_organism_code=restrict_to_organism_code,
    )
    if hit is None:
        return OrthologDecision(hit=None, skipped_reason='no_profiled_ortholog')
    return OrthologDecision(hit=hit, skipped_reason=None)


def get_gene_annotation(
    gene=None, cache_dir='./.cache', profile=None, profile_config=None, organism=None, strain=None,
    locus=None, name=None, gene_name_cache_dir=gene_names.DEFAULT_GENE_NAME_CACHE_DIR,
    allow_online_name_lookup=True, refresh_gene_name_cache=False,
    cache_supplied_name=False,
    allow_ortholog_fallback=False, ortholog_override=None,
    ortholog_catalog=None,
    progress_cb=None,
):
    if locus is None and gene is not None:
        locus = gene
    if profile is None and organism is None:
        profile = 'mtb-h37rv'
    target = targets.resolve_annotation_target(
        profile_identifier=profile,
        organism_identifier=organism,
        strain_identifier=strain,
        locus=locus,
        name=name,
        profile_lookup=_profile_lookup_from_config(profile_config),
        gene_name_cache_dir=gene_name_cache_dir,
        allow_online_name_lookup=allow_online_name_lookup,
    )
    gene = target.resolved_locus
    name = target.resolved_name
    display_gene = target.primary_identifier
    profile_context = target.profile

    gene_name_source = target.gene_name_source
    gene_name_source_detail = target.gene_name_source_detail
    gene_name_confidence = target.gene_name_confidence
    gene_name_aliases = target.gene_name_aliases
    gene_name_candidates = target.gene_name_candidates
    gene_name_warnings = target.gene_name_warnings

    if target.submitted_name is not None:
        gene_name_source = gene_name_source or 'supplied'
        gene_name_source_detail = gene_name_source_detail or 'supplied argument'
        gene_name_confidence = gene_name_confidence or 'curator_supplied'
        if cache_supplied_name and gene is not None and name:
            gene_names.cache_supplied_gene_name(
                profile_context,
                gene,
                name,
                cache_dir=gene_name_cache_dir,
            )
    elif refresh_gene_name_cache and gene is not None:
        lookup_result = gene_names.resolve_gene_name(
            profile_context,
            gene,
            cache_dir=gene_name_cache_dir,
            allow_online_lookup=allow_online_name_lookup,
            refresh_cache=True,
        )
        name = lookup_result.gene_name
        gene_name_source = lookup_result.source
        gene_name_source_detail = lookup_result.source_detail
        gene_name_confidence = lookup_result.confidence
        gene_name_aliases = list(lookup_result.aliases)
        gene_name_candidates = list(lookup_result.candidates)
        gene_name_warnings = list(lookup_result.warnings)

    log.info(
        f'Starting annotation process for {profile_context.canonical_name} gene {display_gene}'
    )
    start = time.time()

    llm_handler = llms.LlmHandler(cache_dir)
    paper_manager = pmc.PmcPaperManager(cache_dir, organism_profile=profile_context)

    direct_pass = run_paper_annotation_pass(
        gene,
        name,
        display_gene,
        profile_context,
        llm_handler=llm_handler,
        paper_manager=paper_manager,
        cache_key=_pmc_mapping_cache_key(profile_context, target),
        evidence_mode='target',
        progress_cb=progress_cb,
    )

    duration = time.time() - start
    log.info(
        f'Finished direct annotation for gene {display_gene} in {utils.seconds_to_str(duration)}'
    )

    llm_usage = llm_handler.summarize_usage()
    gene_distillation = direct_pass.gene_distillation
    ranked_papers = direct_pass.ranked_papers
    selection = direct_pass.selection
    used = direct_pass.used_pmc_ids
    pmids_analyzed = direct_pass.pmids_analyzed
    cumulative_relevance = direct_pass.cumulative_relevance
    pmc_ids = [record.pmc_id for record in ranked_papers]

    annotation_metadata = metadata.build_annotation_metadata(
        gene=gene,
        gene_name=name,
        ranked_records=ranked_papers,
        selected_records=selection.selected_records,
        analyzed_pmc_ids=used,
        pmids_analyzed=pmids_analyzed,
        sections_analyzed=direct_pass.sections_analyzed,
        selection_mode=selection.selection_mode,
        eligible_count=selection.eligible_count,
        cumulative_relevance=cumulative_relevance,
        target_relevance=pmc.DEFAULT_TARGET_RELEVANCE,
        min_papers=pmc.DEFAULT_MIN_PAPERS,
        max_papers=pmc.DEFAULT_MAX_PAPERS,
        duration_sec=duration,
        profile_id=profile_context.profile_id,
        canonical_name=profile_context.canonical_name,
        species_name=profile_context.species_name,
        strain=profile_context.strain,
        gene_name_source=gene_name_source,
        gene_name_source_detail=gene_name_source_detail,
        gene_name_candidates=gene_name_candidates,
        gene_name_confidence=gene_name_confidence,
        gene_name_aliases=gene_name_aliases,
        gene_name_warnings=gene_name_warnings,
        submitted_locus=target.submitted_locus,
        submitted_name=target.submitted_name,
        resolved_locus=target.resolved_locus,
        resolved_name=target.resolved_name,
        profile_source=target.profile_source,
        target_warnings=target.warnings,
        llm_usage=llm_usage,
    )

    merged_annotation = None
    field_coverage = None
    if gene_distillation is not None:
        target_parsed = metadata.null_out_other_locus_claims(
            json.loads(gene_distillation),
            expected_gene_id=gene,
        )
        field_coverage = metadata.build_field_coverage(
            target_parsed,
            profile=profile_context,
        )
        merged_annotation = metadata.merge_annotation_output(
            json.dumps(target_parsed),
            annotation_metadata,
            field_coverage=field_coverage,
        )
        if go_resolution.is_go_resolution_enabled(profile_context):
            _emit_progress(progress_cb, 'target', 'go_resolving')
            target_go_attachment = go_resolution.resolve_for_annotation(
                function=merged_annotation.get('function'),
                functional_category=merged_annotation.get('functional_category'),
                ranker_models=list(MODEL_SUMMARY),
            )
            merged_annotation['go_terms'] = target_go_attachment.go_terms
            merged_annotation['annotation_metadata']['go_resolution'] = (
                target_go_attachment.resolution
            )

    profile_field_defs = field_defs.resolve_annotation_field_defs(profile_context)
    eligible_fields = []
    if merged_annotation is not None:
        eligible_fields = metadata.fields_eligible_for_ortholog(profile_field_defs)

    decision = _decide_ortholog_action(
        allow_ortholog_fallback=allow_ortholog_fallback,
        ortholog_override=ortholog_override,
        cumulative_relevance=cumulative_relevance,
        kegg_code=profile_context.kegg_organism_code,
        gene=gene,
        cache_dir=cache_dir,
        profile_config=profile_config,
        ortholog_catalog=ortholog_catalog,
        kegg_locus_regex=profile_context.kegg_locus_regex,
    )
    ortholog_hit = decision.hit
    ortholog_pass_metadata = metadata.build_ortholog_pass_metadata(
        ran=False,
        skipped_reason=decision.skipped_reason,
        fields_requested=eligible_fields,
    )

    if merged_annotation is None or not eligible_fields:
        if ortholog_hit is not None:
            ortholog_pass_metadata = metadata.build_ortholog_pass_metadata(
                ran=False,
                skipped_reason='no_eligible_fields',
                fields_requested=[],
            )
    elif ortholog_hit is not None:
        ortholog_gene = ortholog_hit.source_gene_id
        ortholog_name = orthology.resolve_ortholog_gene_name(
            ortholog_hit,
            gene_name_cache_dir,
            allow_online_lookup=allow_online_name_lookup,
            target_gene_name=name,
        )
        ortholog_profile = orthology.profile_for_kegg_organism(
            ortholog_hit.source_organism_code,
            extra_profiles=ortholog_catalog,
        )
        ortholog_context = {
            'target_gene_id': gene,
            'target_gene_name': name or display_gene,
            'ortholog_gene_id': ortholog_gene,
            'ortholog_gene_name': ortholog_name,
        }
        log.info(
            'Running ortholog paper pass for %s using %s:%s (search name %r)',
            display_gene, ortholog_hit.source_organism_code, ortholog_gene, ortholog_name,
        )
        ortholog_paper_manager = pmc.PmcPaperManager(cache_dir, organism_profile=ortholog_profile)
        ortholog_pass = run_paper_annotation_pass(
            ortholog_gene,
            ortholog_name,
            ortholog_gene,
            ortholog_profile,
            llm_handler=llm_handler,
            paper_manager=ortholog_paper_manager,
            cache_key=None,
            evidence_mode='ortholog',
            ortholog_context=ortholog_context,
            save_pmc_mapping=False,
            field_defs_profile=profile_context,
            progress_cb=progress_cb,
        )
        if ortholog_pass.gene_distillation is None:
            ortholog_pass_metadata = metadata.build_ortholog_pass_metadata(
                ran=True,
                skipped_reason='no_ortholog_papers',
                fields_requested=eligible_fields,
            )
        else:
            # Ortholog pass uses the same LLM inference path as the target;
            # only ortholog_allowed fields may be copied onto the target annotation.
            ortholog_parsed = metadata.null_out_other_locus_claims(
                json.loads(ortholog_pass.gene_distillation),
                expected_gene_id=ortholog_gene,
            )
            ortholog_go_attachment = None
            if go_resolution.is_go_resolution_enabled(profile_context):
                _emit_progress(progress_cb, 'ortholog', 'go_resolving')
                ortholog_go_attachment = go_resolution.resolve_for_annotation(
                    function=ortholog_parsed.get('function'),
                    functional_category=ortholog_parsed.get('functional_category'),
                    ranker_models=list(MODEL_SUMMARY),
                )
            merged_annotation, fields_filled = metadata.merge_ortholog_annotation(
                merged_annotation,
                ortholog_parsed,
                eligible_fields,
                ortholog_hit,
                target_gene_id=gene,
                target_gene_name=name or display_gene,
            )
            if ortholog_go_attachment is not None:
                # Ortholog GO is stored separately from the target's go_terms so
                # the target attachment above is never overwritten here.
                merged_annotation['annotation_metadata']['ortholog_go_terms'] = (
                    ortholog_go_attachment.go_terms
                )
                merged_annotation['annotation_metadata']['ortholog_go_resolution'] = (
                    ortholog_go_attachment.resolution
                )
            if fields_filled:
                field_coverage = metadata.build_field_coverage(
                    merged_annotation, profile=profile_context,
                )
                merged_annotation['annotation_metadata']['field_coverage'] = field_coverage
            ortholog_pass_metadata = metadata.build_ortholog_pass_metadata(
                ran=True,
                skipped_reason=None if fields_filled else 'ortholog_fields_still_null',
                fields_requested=eligible_fields,
                fields_filled=fields_filled,
                papers_analyzed=[f'PMC{pmc_id}' for pmc_id in ortholog_pass.used_pmc_ids],
                pmids_analyzed=ortholog_pass.pmids_analyzed,
            )
            llm_usage = llm_handler.summarize_usage()
            merged_annotation['annotation_metadata']['llm_usage'] = llm_usage
            annotation_metadata['llm_usage'] = llm_usage

    if merged_annotation is not None:
        merged_annotation = metadata.attach_ortholog_metadata(
            merged_annotation,
            ortholog_hit,
            ortholog_pass_metadata,
        )
    elif gene_distillation is None:
        annotation_metadata['ortholog_top_hit'] = (
            ortholog_hit.to_metadata() if ortholog_hit is not None else None
        )
        annotation_metadata['ortholog_pass'] = ortholog_pass_metadata

    duration = time.time() - start
    log.info(
        f'Finished annotation process for gene {display_gene} in {utils.seconds_to_str(duration)}'
    )

    return {
        "gene_distillation": gene_distillation,
        "gene_annotation": merged_annotation,
        "pmc_ids": pmc_ids,
        "used_ids": used,
        "cumulative_relevance": cumulative_relevance,
        "selection_mode": selection.selection_mode,
        "annotation_metadata": annotation_metadata,
    }
