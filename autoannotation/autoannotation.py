import logging
import time

import pandas as pd

import llms
import pmc
import utils

from models import MODEL_SUMMARY, MODEL_AGGREGATION, MODEL_CONSENSUS

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

    pmc_ids = paper_manager.get_pmc_ids(gene, name)
    paper_manager.save_gene_pmc_ids(gene, pmc_ids)
    section_distillation_candidates = []
    section_distillations = []

    if len(pmc_ids) < 3:
        log.warning(f'Found only {len(pmc_ids)} paper{utils.s_if_plural(pmc_ids)} for gene {gene}')

    for pmc_id in pmc_ids:
        sections = []

        # filter based on established paper relevance criteria
        if not paper_manager.is_relevant(pmc_id, gene, name):
            log.info(f'Skipping paper PMC{pmc_id}: does not pass relevance checks for gene {gene}')
            continue
        else:
            log.info(f'Starting inference process for gene {gene} with paper PMC{pmc_id}')

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
                    gene, name, section, model
                )
                section_distillation_candidates_cur.append(section_distillation_candidate)
                section_distillation_candidates.append((
                    f'PMC{pmc_id}', label, model, gene, name, section_distillation_candidate,
                    duration_sec
                ))
            section_distillation, duration_sec = llm_handler.get_llm_consensus_json(
                section_distillation_candidates_cur[0], section_distillation_candidates_cur[1],
                section_distillation_candidates_cur[2], model=MODEL_CONSENSUS
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

    if len(section_distillation_filtered_df) > 1:
        gene_distillation, duration_sec = llm_handler.get_llm_aggregate_json(
            section_distillation_filtered_df['Response'],
            section_distillation_filtered_df['PMID'],
            model=MODEL_AGGREGATION
        )
    elif len(section_distillation_filtered_df) == 1:
        gene_distillation = section_distillation_filtered_df['Response'].iat[0]
    else:
        gene_distillation = None

    duration = time.time() - start
    log.info(
        f'Finished annotation process for gene {gene} in {utils.seconds_to_str(duration)}'
    )

    return gene_distillation
