from goresolve.aliases import CATEGORY_ALIASES
from goresolve.ontology import GoOntology, _normalize_label
from goresolve.types import GoCandidate

_SOURCE_PRIORITY = {'exact': 0, 'alias': 1}


def build_queries(function, functional_category) -> tuple[str, ...]:
    queries = []
    if functional_category:
        for item in functional_category:
            if isinstance(item, str) and item.strip():
                queries.append(item.strip())
    if isinstance(function, str) and function.strip():
        queries.append(function.strip())
    return tuple(queries)


def exact_and_alias_candidates(ontology: GoOntology, queries) -> list[GoCandidate]:
    best_by_id: dict[str, GoCandidate] = {}

    for query in queries:
        if not isinstance(query, str) or not query.strip():
            continue
        normalized = _normalize_label(query)

        for go_id in ontology.label_index.get(normalized, ()):
            if go_id not in ontology.terms:
                continue
            _add_candidate(best_by_id, ontology, go_id, 'exact')

        for go_id in CATEGORY_ALIASES.get(normalized, ()):
            if go_id not in ontology.terms:
                continue
            _add_candidate(best_by_id, ontology, go_id, 'alias')

    return list(best_by_id.values())


def _add_candidate(
    best_by_id: dict[str, GoCandidate],
    ontology: GoOntology,
    go_id: str,
    source: str,
) -> None:
    existing = best_by_id.get(go_id)
    if existing and _SOURCE_PRIORITY[existing.source] <= _SOURCE_PRIORITY[source]:
        return

    term = ontology.terms[go_id]
    best_by_id[go_id] = GoCandidate(
        id=go_id,
        name=term.name,
        aspect=term.aspect,
        definition=term.definition,
        score=1.0,
        source=source,
    )
