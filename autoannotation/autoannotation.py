import json
import logging
import time

import pandas as pd

from . import llms
from . import metadata
from . import pmc
from . import utils

from .models import MODEL_SUMMARY, MODEL_AGGREGATION, MODEL_CONSENSUS

logging.basicConfig(format='%(asctime)s %(levelname).1s | %(message)s')
log = logging.getLogger(__name__)
log.setLevel(logging.DEBUG)

def get_gene_annotation(gene, cache_dir='./.cache'):
    log.info(f'Starting annotation process for gene {gene}')
    start = time.time()
    llm_handler = llms.LlmHandler(cache_dir)
    paper_manager = pmc.PmcPaperManager(cache_dir)

    mycobrowser_df = pd.read_csv(
        './Mycobacterium_tuberculosis_H37Rv_txt_v5.txt',
        sep='\t'
    )
    mycobrowser_df = mycobrowser_df.loc[
        mycobrowser_df['Feature'].eq('CDS'), :
    ].set_index(
        'Locus', drop=True
    ).sort_index()

    name = mycobrowser_df.at[gene, 'Name']

    ranked_papers = paper_manager.get_ranked_papers(gene, name)
    pmc_ids = [record.pmc_id for record in ranked_papers]
    paper_manager.save_gene_pmc_ids(gene, pmc_ids)
    section_distillation_candidates = []
    section_distillations = []

    if len(pmc_ids) < 3:
        log.warning(f'Found only {len(pmc_ids)} paper{utils.s_if_plural(pmc_ids)} for gene {gene}')

    # speeding up analysis
    #pmc_ids = pmc_ids[:25]

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
            f'Limited literature for gene {gene}: analyzing all '
            f'{len(papers_to_analyze)} eligible paper{utils.s_if_plural(papers_to_analyze)} '
            f'(fewer than minimum {pmc.DEFAULT_MIN_PAPERS})'
        )

    used = []
    relevance_by_pmc_id = {
        record.pmc_id: record
        for record in ranked_papers
    }

    for pmc_id in papers_to_analyze:
        sections = []

        relevance_record = relevance_by_pmc_id.get(pmc_id)
        relevance_score = relevance_record.score if relevance_record is not None else 0.0
        log.info(
            f'Starting inference process for gene {gene} with paper PMC{pmc_id} '
            f'(relevance score {relevance_score:.3f})'
        )
        used.append(pmc_id)

        abstract = paper_manager.get_abstract(pmc_id)
        if abstract is not None:
            sections.append(('abstract', abstract))
        results = paper_manager.get_results(pmc_id)
        if results is not None:
            sections.append(('results', results))
        discussion = paper_manager.get_discussion(pmc_id)
        if discussion is not None and discussion != results:
            sections.append(('discussion', discussion))

        log.debug(
            f'Obtained {len(sections)} relevant section{utils.s_if_plural(sections)} for ' + \
                f'paper PMC{pmc_id}'
        )

        for label, section in sections:
            log.debug(f'Starting processing for PMC{pmc_id} {label}')
            section_distillation_candidates_cur = []
            for model in (MODEL_SUMMARY): #for model in ('mistral-nemo:12b', 'llama3:8b', 'gemma3:12b'):
                section_distillation_candidate, duration_sec = llm_handler.get_llm_gene_info_json(
                    gene, name, section, model, section_type=label,
                )
                section_distillation_candidates_cur.append(section_distillation_candidate)
                section_distillation_candidates.append((
                    f'PMC{pmc_id}', label, model, gene, name, section_distillation_candidate,
                    duration_sec
                ))
            section_distillation, duration_sec = llm_handler.get_llm_consensus_json(
                section_distillation_candidates_cur[0], section_distillation_candidates_cur[1],
                section_distillation_candidates_cur[2], model=MODEL_CONSENSUS,
                section_type=label,
            )
            section_distillations.append((
                f'PMC{pmc_id}', label, MODEL_CONSENSUS, gene, name, section_distillation, duration_sec
            ))

    section_distillation_candidate_df = pd.DataFrame(
        section_distillation_candidates,
        columns=['PmcId', 'SectionType', 'Model', 'Gene', 'GeneName', 'Response', 'LlmDur'],
    )

    section_distillation_df = pd.DataFrame(
        section_distillations,
        columns=['PmcId', 'SectionType', 'Model', 'Gene', 'GeneName', 'Response', 'LlmDur'],
    )
    log.debug(' '.join((
        'Finished paper distillation by LLM with',
        str(len(section_distillation_candidate_df)),
        'total summaries generated for',
        str(len(section_distillation_df)),
        f'total paper section{utils.s_if_plural(section_distillation_df)} for gene',
        gene
    )))
    section_distillation_df.insert(
        1, 'PMID', section_distillation_df['PmcId'].map(paper_manager.get_pmid)
    )

    section_distillation_filtered_df = section_distillation_df.loc[
        section_distillation_df['Response'].map(llm_handler.json_regex_filter),
        :
    ]
    log.debug(
        f'Filtered down to {len(section_distillation_filtered_df)} valid ' +\
            f'section{utils.s_if_plural(section_distillation_filtered_df)} for gene {gene}'
    )

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

    if len(section_distillation_filtered_df) >= 1:
        def _relevance_for_pmc_label(pmc_label):
            pmc_id = str(pmc_label).removeprefix('PMC')
            record = relevance_by_pmc_id.get(pmc_id)
            return record.score if record is not None else None

        relevance_scores = section_distillation_filtered_df['PmcId'].map(_relevance_for_pmc_label)
        gene_distillation, duration_sec = llm_handler.get_llm_aggregate_json(
            section_distillation_filtered_df['Response'],
            section_distillation_filtered_df['PMID'],
            model=MODEL_AGGREGATION,
            literature_context=literature_context,
            relevance_scores=relevance_scores.tolist(),
        )
    else:
        gene_distillation = None

    duration = time.time() - start
    log.info(
        f'Finished annotation process for gene {gene} in {utils.seconds_to_str(duration)}'
    )

    annotation_metadata = metadata.build_annotation_metadata(
        gene=gene,
        gene_name=name,
        ranked_records=ranked_papers,
        selected_records=selection.selected_records,
        analyzed_pmc_ids=used,
        pmids_analyzed=pmids_analyzed,
        sections_analyzed=len(section_distillation_filtered_df),
        selection_mode=selection.selection_mode,
        eligible_count=selection.eligible_count,
        cumulative_relevance=cumulative_relevance,
        target_relevance=pmc.DEFAULT_TARGET_RELEVANCE,
        min_papers=pmc.DEFAULT_MIN_PAPERS,
        max_papers=pmc.DEFAULT_MAX_PAPERS,
        duration_sec=duration,
    )

    merged_annotation = None
    if gene_distillation is not None:
        field_coverage = metadata.build_field_coverage(json.loads(gene_distillation))
        merged_annotation = metadata.merge_annotation_output(
            gene_distillation,
            annotation_metadata,
            field_coverage=field_coverage,
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
