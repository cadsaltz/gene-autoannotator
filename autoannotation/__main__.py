import argparse
import json
import sys
import os


from autoannotation.autoannotation import get_gene_annotation
from autoannotation import gene_names

# CLI and backend entry point for a single annotation run. The output path
# convention intentionally preserves legacy MTB files at gen_json/gen_<locus>.json
# while namespacing newer organism profiles by profile_id.
def main(
    gene=None, cache_dir='./.cache', profile=None, profile_config=None, organism=None, strain=None,
    locus=None, name=None, output_dir='gen_json',
    gene_name_cache=gene_names.DEFAULT_GENE_NAME_CACHE_DIR,
    no_online_name_lookup=False,
    refresh_gene_name_cache=False,
    cache_supplied_name=False,
    allow_ortholog_fallback=False,
    ortholog_override=None,
    ortholog_catalog=None,
    quiet=None,
):
    if quiet is None:
        quiet = bool(os.getenv('ANNOTATION_JOB_ID'))
    if profile and organism:
        raise ValueError('use either profile or organism, not both')
    result = get_gene_annotation(
        gene=gene,
        cache_dir=cache_dir,
        profile=profile,
        profile_config=profile_config,
        organism=organism,
        strain=strain,
        locus=locus,
        name=name,
        gene_name_cache_dir=gene_name_cache,
        allow_online_name_lookup=not no_online_name_lookup,
        refresh_gene_name_cache=refresh_gene_name_cache,
        cache_supplied_name=cache_supplied_name,
        allow_ortholog_fallback=allow_ortholog_fallback,
        ortholog_override=ortholog_override,
        ortholog_catalog=ortholog_catalog,
    )

    if result is None:
        return

    output_gene = locus or gene or name
    pmc_ids = result["pmc_ids"]
    used = result["used_ids"]
    parsed = result.get("gene_annotation")

    if parsed is None:
        if result.get("gene_distillation") is None:
            if not quiet:
                print(f"No annotation produced for {output_gene}")
            return
        parsed = json.loads(result["gene_distillation"])

    if output_gene is None:
        output_gene = parsed.get("gene_id") or parsed.get("rv_id")

    if not quiet:
        print(output_gene, json.dumps(parsed, indent=2))
        print(f"Number of papers used: {len(used)}")
        print(f"Selection mode: {result.get('selection_mode', 'unknown')}")

    profile_id = parsed.get("annotation_metadata", {}).get("profile_id", "mtb-h37rv")
    output_parent = output_dir
    # Non-MTB profiles may share locus-like names across organisms; separating
    # by profile_id keeps generated artifacts unambiguous without changing the
    # original MTB output contract.
    if profile_id != "mtb-h37rv":
        output_parent = os.path.join(output_parent, profile_id)
    os.makedirs(output_parent, exist_ok=True)

    safe_output_gene = str(output_gene).replace("/", "_").replace(" ", "_")
    output_path = os.path.join(output_parent, f"gen_{safe_output_gene}.json")

    with open(output_path, "w") as f:
        json.dump(parsed, f, indent=2)

    return {
        "annotation": parsed,
        "papers_used": used,
        "all_papers": pmc_ids,
        "output_path": output_path,
        "cumulative_relevance": result.get("cumulative_relevance", 0.0),
        "selection_mode": result.get("selection_mode"),
    }

if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description=(
            'Utility for inferring gene information for a given gene from published literature '
            'using LLMs.'
        )
    )

    parser.add_argument('gene',
        nargs='?',
        help='Legacy MTB gene locus shorthand, e.g. Rv0001.',
    )

    parser.add_argument('--profile',
        help='Configured organism profile, e.g. mtb-h37rv or tcruzi-clbrener.',
    )

    parser.add_argument('--organism',
        help='Organism/species name or synonym.',
    )

    parser.add_argument('--strain',
        help='Optional strain/isolate/reference name or synonym.',
    )

    parser.add_argument('--locus',
        help='Gene locus to gather and summarize information on.',
    )

    parser.add_argument('--name',
        help='Optional gene name/symbol for paper retrieval and prompts.',
    )

    parser.add_argument('-c', '--cache-dir',
        default='./.cache',
        help=(
            'The directory where paper contents should be written (and read from, if already '
            'present). Default is %(default)s.'
        )
    )

    parser.add_argument('--gene-name-cache',
        default=gene_names.DEFAULT_GENE_NAME_CACHE_DIR,
        help='Directory for cached locus-to-gene-name records.',
    )

    parser.add_argument('--no-online-name-lookup',
        action='store_true',
        help='Disable NCBI/UniProt gene-name lookup before annotation.',
    )

    parser.add_argument('--refresh-gene-name-cache',
        action='store_true',
        help='Ignore cached online gene-name records and refresh from online sources.',
    )

    parser.add_argument('--cache-supplied-name',
        action='store_true',
        help='Write --name into the gene-name cache as a manual curated record.',
    )

    parser.add_argument('--output-dir',
        default='gen_json',
        help='Directory where generated annotation JSON should be written.',
    )

    args = parser.parse_args(sys.argv[1:])
    args_dict = vars(args)
    main(**args_dict)
