import os

from shared.job_contract import AnnotationJobRequest


def _load_annotation_main():
    from autoannotation import __main__ as annotation_cli

    return annotation_cli.main


def run_annotation_job(request: AnnotationJobRequest, annotation_main=None):
    # Phase 1 runs the pipeline in-process (identical to the legacy runner).
    # Subprocess isolation is a Phase 2 hardening step; the annotation logic is
    # unchanged either way.
    main = annotation_main or _load_annotation_main()
    # Override paths from worker env, ignoring coordinator-sent paths for security.
    cache_dir = os.getenv("WORKER_CACHE_DIR", "./.cache")
    output_dir = os.getenv("WORKER_OUTPUT_DIR", "gen_json")
    return main(
        gene=None,
        profile=request.profile,
        profile_config=request.profile_config,
        organism=request.organism,
        strain=request.strain,
        locus=request.locus,
        name=request.name,
        cache_dir=cache_dir,
        output_dir=output_dir,
        gene_name_cache=request.gene_name_cache,
        no_online_name_lookup=not request.allow_online_name_lookup,
        refresh_gene_name_cache=request.refresh_gene_name_cache,
        cache_supplied_name=request.cache_supplied_name,
        allow_ortholog_fallback=request.allow_ortholog_fallback,
        ortholog_override=(
            request.ortholog_override.model_dump()
            if request.ortholog_override is not None
            else None
        ),
    )
