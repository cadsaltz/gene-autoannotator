from goresolve.types import GoResolutionResult

def has_usable_text(function, functional_category) -> bool:
    if isinstance(function, str) and function.strip():
        return True
    if functional_category:
        return any(isinstance(c, str) and c.strip() for c in functional_category)
    return False

def resolve_go_terms(*, function, functional_category, ontology_path, embedder,
                     ranker_models, rank_fn=None, top_k=25, min_cosine=0.35):
    if not has_usable_text(function, functional_category):
        return GoResolutionResult(
            go_terms=(),
            method='skipped_no_text',
            queries=(),
            shortlist=(),
            votes=(),
            notes='No usable function or functional_category text.',
        )
    raise NotImplementedError('full resolve path comes in later tasks')
