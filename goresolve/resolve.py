from goresolve.consensus import majority_go_ids
from goresolve.hierarchy import drop_ancestor_terms
from goresolve.ontology import load_go_ontology
from goresolve.rank import rank_go_terms
from goresolve.retrieve import build_queries, build_shortlist
from goresolve.types import GoResolutionResult, ResolvedGoTerm


def has_usable_text(function, functional_category) -> bool:
    if isinstance(function, str) and function.strip():
        return True
    if functional_category:
        return any(isinstance(c, str) and c.strip() for c in functional_category)
    return False

def resolve_go_terms(*, function, functional_category, ontology_path, embedder,
                     ranker_models, rank_fn=None, top_k=25, min_cosine=0.35,
                     max_categories: int | None = 8):
    cleaned_categories = list(
        build_queries(
            None,
            functional_category,
            max_categories=max_categories,
        )
    )
    function_queries = build_queries(function, None)
    cleaned_function = function_queries[0] if function_queries else None
    queries = tuple(cleaned_categories) + function_queries

    if not has_usable_text(cleaned_function, cleaned_categories):
        return GoResolutionResult(
            go_terms=(),
            method='skipped_no_text',
            queries=(),
            shortlist=(),
            votes=(),
            notes='No usable function or functional_category text.',
        )

    ontology = load_go_ontology(ontology_path)
    shortlist = build_shortlist(
        ontology,
        queries=queries,
        embedder=embedder,
        top_k=top_k,
        min_cosine=min_cosine,
    )
    if not shortlist:
        return GoResolutionResult(
            go_terms=(),
            method='no_candidates',
            queries=queries,
            shortlist=(),
            votes=(),
        )

    shortlist_tuple = tuple(shortlist)
    if not ranker_models:
        terms = tuple(
            ResolvedGoTerm(
                id=candidate.id,
                name=candidate.name,
                aspect=candidate.aspect,
                confidence=1.0,
                method='exact_label' if candidate.source == 'exact' else candidate.source,
                sources=queries,
                agreement=None,
            )
            for candidate in shortlist
            if candidate.source in {'exact', 'alias'}
        )
        return GoResolutionResult(
            go_terms=terms,
            method='exact_only',
            queries=queries,
            shortlist=shortlist_tuple,
            votes=(),
        )

    votes = []
    for model in ranker_models:
        ids = rank_go_terms(
            function=cleaned_function,
            functional_category=cleaned_categories,
            shortlist=shortlist,
            model=model,
            rank_fn=rank_fn,
        )
        votes.append({'model': model, 'ids': ids})

    winners = majority_go_ids(
        [vote['ids'] for vote in votes],
        n_models=len(ranker_models),
    )
    winner_ids = [go_id for go_id, _, _ in winners]
    compressed_ids = drop_ancestor_terms(winner_ids, ontology)
    dropped_count = len(winner_ids) - len(compressed_ids)
    kept_ids = set(compressed_ids)
    winners = [
        winner
        for winner in winners
        if winner[0] in kept_ids
    ]
    candidates_by_id = {candidate.id: candidate for candidate in shortlist}
    go_terms = tuple(
        ResolvedGoTerm(
            id=go_id,
            name=candidates_by_id[go_id].name,
            aspect=candidates_by_id[go_id].aspect,
            confidence=confidence,
            method='rag_llm_majority',
            sources=queries,
            agreement=agreement,
        )
        for go_id, agreement, confidence in winners
        if go_id in candidates_by_id
    )
    return GoResolutionResult(
        go_terms=go_terms,
        method='rag_llm_majority',
        queries=queries,
        shortlist=shortlist_tuple,
        votes=tuple(votes),
        notes=(
            f'Dropped {dropped_count} ancestor GO terms after majority.'
            if dropped_count
            else ''
        ),
    )
