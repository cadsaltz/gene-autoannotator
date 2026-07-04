from .schemas import AnnotationJobRequest


def _load_annotation_main():
    from autoannotation import __main__ as annotation_cli

    return annotation_cli.main


def run_annotation_job(request: AnnotationJobRequest, annotation_main=None):
    # The backend delegates directly to the CLI function in-process. This keeps
    # web and CLI behavior identical, but it is not a security/resource boundary.
    main = annotation_main or _load_annotation_main()
    return main(
        gene=None,
        profile=request.profile,
        profile_config=request.profile_config,
        organism=request.organism,
        strain=request.strain,
        locus=request.locus,
        name=request.name,
        cache_dir=request.cache_dir,
        output_dir=request.output_dir,
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
