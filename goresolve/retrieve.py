from goresolve.aliases import CATEGORY_ALIASES
from goresolve.query_clean import clean_query_text
from goresolve.embeddings import Embedder, cosine_topk
from goresolve.ontology import GoOntology, _normalize_label
from goresolve.types import GoCandidate

_SOURCE_PRIORITY = {'exact': 0, 'alias': 1, 'embedding': 2}

_EMBED_INDEX_CACHE: dict[tuple[frozenset[str], tuple], 'OntologyEmbeddingIndex'] = {}


class OntologyEmbeddingIndex:
    def __init__(self, ontology: GoOntology, embedder: Embedder):
        documents = ontology.iter_embed_documents()
        self.doc_ids = [go_id for go_id, _ in documents]
        texts = [text for _, text in documents]
        self.doc_vecs = embedder.encode(texts)


def _embedder_cache_key(embedder: Embedder) -> tuple:
    dim = getattr(embedder, 'dim', None)
    if dim is not None:
        return ('fake', dim)
    model_name = getattr(embedder, '_model_name', None)
    if model_name is not None:
        return ('sentence_transformer', model_name)
    return (type(embedder).__name__,)


def _get_embedding_index(ontology: GoOntology, embedder: Embedder) -> OntologyEmbeddingIndex:
    key = (frozenset(ontology.terms.keys()), _embedder_cache_key(embedder))
    cached = _EMBED_INDEX_CACHE.get(key)
    if cached is None:
        cached = OntologyEmbeddingIndex(ontology, embedder)
        _EMBED_INDEX_CACHE[key] = cached
    return cached


def build_queries(
    function,
    functional_category,
    *,
    max_categories: int | None = 8,
) -> tuple[str, ...]:
    categories: list[str] = []
    if functional_category:
        for item in functional_category:
            if isinstance(item, str):
                cleaned = clean_query_text(item)
                if cleaned:
                    categories.append(cleaned)
    if max_categories is not None and len(categories) > max_categories:
        categories = categories[:max_categories]

    queries = list(categories)
    if isinstance(function, str):
        cleaned = clean_query_text(function)
        if cleaned:
            queries.append(cleaned)
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


def embedding_candidates(
    ontology: GoOntology,
    queries,
    embedder: Embedder,
    *,
    top_k: int,
    min_cosine: float,
) -> list[GoCandidate]:
    query_texts = [q.strip() for q in queries if isinstance(q, str) and q.strip()]
    if not query_texts:
        return []

    index = _get_embedding_index(ontology, embedder)
    query_vecs = embedder.encode(query_texts)
    hits = cosine_topk(
        query_vecs,
        index.doc_vecs,
        index.doc_ids,
        top_k=top_k,
        min_cosine=min_cosine,
    )

    candidates: list[GoCandidate] = []
    for go_id, score in hits:
        term = ontology.terms[go_id]
        candidates.append(
            GoCandidate(
                id=go_id,
                name=term.name,
                aspect=term.aspect,
                definition=term.definition,
                score=score,
                source='embedding',
            )
        )
    return candidates


def build_shortlist(
    ontology: GoOntology,
    *,
    queries,
    embedder: Embedder,
    top_k: int,
    min_cosine: float,
) -> list[GoCandidate]:
    exact_alias = exact_and_alias_candidates(ontology, queries)
    exact_alias.sort(key=lambda c: (_SOURCE_PRIORITY[c.source], -c.score))

    seen = {c.id for c in exact_alias}
    shortlist = list(exact_alias)

    if len(shortlist) >= top_k:
        return shortlist[:top_k]

    for candidate in embedding_candidates(
        ontology,
        queries,
        embedder,
        top_k=top_k,
        min_cosine=min_cosine,
    ):
        if candidate.id in seen:
            continue
        shortlist.append(candidate)
        seen.add(candidate.id)
        if len(shortlist) >= top_k:
            break

    return shortlist


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
