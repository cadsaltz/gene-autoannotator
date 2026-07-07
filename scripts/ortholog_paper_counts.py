#!/usr/bin/env python3
"""Lightweight ortholog PubMed raw hit counts (no full paper parse)."""

import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from autoannotation import orthology
from autoannotation import targets
from autoannotation.pmc import PmcPaperManager


def count_raw_papers(gene, name, profile, cache_dir="./.cache"):
    pm = PmcPaperManager(cache_dir, organism_profile=profile)
    sources = pm.get_pmc_id_sources(gene, name)
    name_term = pm._build_name_search_term(name) if name and name != gene else None
    return {
        "raw_pmc_ids": len(sources),
        "name_term": name_term,
        "species": profile.species_name,
    }


def main():
    genes = sys.argv[1:] or [
        "Rv0001", "Rv0002", "Rv2007c", "Rv2057c", "Rv2070c",
        "Rv2418c", "Rv2612c", "Rv3407",
    ]
    rows = []
    for locus in genes:
        target = targets.resolve_annotation_target(
            profile_identifier="mtb-h37rv",
            organism_identifier=None,
            strain_identifier=None,
            locus=locus,
            name=None,
        )
        hit = orthology.lookup_top_ortholog(
            target.profile.kegg_organism_code,
            target.resolved_locus,
        )
        row = {
            "locus": locus,
            "target_name": target.resolved_name,
            "target_raw": count_raw_papers(
                target.resolved_locus,
                target.resolved_name,
                target.profile,
            ),
        }
        if hit:
            orth_name = hit.source_gene_name or hit.source_gene_id
            orth_profile = orthology.profile_for_kegg_organism(hit.source_organism_code)
            row["ortholog"] = {
                "org": hit.source_organism_code,
                "gene": hit.source_gene_id,
                "name": orth_name,
                "score": hit.score,
                **count_raw_papers(hit.source_gene_id, orth_name, orth_profile),
            }
        rows.append(row)
    print(json.dumps(rows, indent=2))


if __name__ == "__main__":
    main()
