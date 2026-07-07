#!/usr/bin/env python3
"""Diagnostic script for ortholog vs target PubMed retrieval (no LLM)."""

import json
import sys
from dataclasses import asdict
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from autoannotation import gene_names
from autoannotation import organisms
from autoannotation import orthology
from autoannotation import targets
from autoannotation.pmc import PmcPaperManager


GENES = [
    "Rv0001",   # dnaA - replication enzyme
    "Rv2007c",  # fdxA - ferredoxin (user case)
    "Rv2057c",  # stress
    "Rv2070c",  # stress
    "Rv2418c",  # low paper count
    "Rv2612c",  # essentiality candidate
    "Rv3221A",  # alternate locus form
    "Rv3407",   # hypothetical/enzyme
]


def summarize_papers(records, limit=5):
    selected = records[:limit]
    return {
        "total_ranked": len(records),
        "top": [
            {
                "pmc_id": r.pmc_id,
                "pmid": r.pmid,
                "score": round(r.score, 3),
                "sources": r.retrieval_sources,
                "warnings": r.warnings,
                "title": (r.title or "")[:120],
            }
            for r in selected
        ],
    }


def inspect_search_terms(paper_manager, gene, name):
    locus_term = f"{gene}[title]+OR+{gene}[abstract]"
    name_term = None
    if name and name != gene:
        name_term = paper_manager._build_name_search_term(name)
    return {"locus_term": locus_term, "name_term": name_term}


def analyze_gene(locus, cache_dir="./.cache"):
    target = targets.resolve_annotation_target(
        profile_identifier="mtb-h37rv",
        organism_identifier=None,
        strain_identifier=None,
        locus=locus,
        name=None,
    )
    gene = target.resolved_locus
    name = target.resolved_name
    profile = target.profile

    target_pm = PmcPaperManager(cache_dir, organism_profile=profile)
    target_sources = target_pm.get_pmc_id_sources(gene, name)
    target_ranked = target_pm.get_ranked_papers(gene, name)
    target_selection = target_pm.select_relevance_records(target_ranked)

    ortholog_hit = orthology.lookup_top_ortholog(
        profile.kegg_organism_code,
        gene,
        cache_dir=cache_dir,
    )

    ortholog_block = None
    if ortholog_hit:
        ortholog_name = orthology.resolve_ortholog_gene_name(
            ortholog_hit,
            gene_names.DEFAULT_GENE_NAME_CACHE_DIR,
            allow_online_lookup=False,
            target_gene_name=target.resolved_name,
        )
        ortholog_profile = orthology.profile_for_kegg_organism(
            ortholog_hit.source_organism_code
        )
        ortholog_pm = PmcPaperManager(cache_dir, organism_profile=ortholog_profile)
        ortholog_sources = ortholog_pm.get_pmc_id_sources(
            ortholog_hit.source_gene_id,
            ortholog_name,
        )
        ortholog_ranked = ortholog_pm.get_ranked_papers(
            ortholog_hit.source_gene_id,
            ortholog_name,
        )
        ortholog_selection = ortholog_pm.select_relevance_records(ortholog_ranked)
        ortholog_block = {
            "hit": ortholog_hit.to_metadata(),
            "resolved_name": ortholog_name,
            "profile": {
                "profile_id": ortholog_profile.profile_id,
                "species_name": ortholog_profile.species_name,
                "locus_regex": ortholog_profile.locus_regex,
                "target_patterns": list(ortholog_profile.target_patterns),
            },
            "search_terms": inspect_search_terms(
                ortholog_pm,
                ortholog_hit.source_gene_id,
                ortholog_name,
            ),
            "raw_pmc_ids": len(ortholog_sources),
            "retrieval_sources": {
                k: sorted(v) for k, v in ortholog_sources.items()
            },
            "papers": summarize_papers(ortholog_ranked),
            "selection": {
                "mode": ortholog_selection.selection_mode,
                "eligible": ortholog_selection.eligible_count,
                "selected": len(ortholog_selection.selected_records),
                "total_retrieved": ortholog_selection.total_retrieved,
            },
            "would_aggregate": len(ortholog_selection.selected_records) >= 1,
        }

    return {
        "locus": locus,
        "resolved_name": name,
        "target": {
            "search_terms": inspect_search_terms(target_pm, gene, name),
            "raw_pmc_ids": len(target_sources),
            "papers": summarize_papers(target_ranked),
            "selection": {
                "mode": target_selection.selection_mode,
                "eligible": target_selection.eligible_count,
                "selected": len(target_selection.selected_records),
                "total_retrieved": target_selection.total_retrieved,
            },
        },
        "ortholog": ortholog_block,
    }


def main():
    genes = sys.argv[1:] or GENES
    results = [analyze_gene(gene) for gene in genes]
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
