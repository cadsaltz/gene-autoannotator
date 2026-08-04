from __future__ import annotations

import os
from dataclasses import dataclass

from goresolve import has_usable_text, resolve_go_terms
from goresolve.embeddings import SentenceTransformerEmbedder


@dataclass(frozen=True)
class GoResolutionAttachment:
    go_terms: list[dict]
    resolution: dict


def is_go_resolution_enabled(profile) -> bool:
    return bool(getattr(profile, "go_resolution_enabled", False))


def resolve_for_annotation(
    *,
    function,
    functional_category,
    ranker_models: list[str],
    ontology_path: str | None = None,
    embedder=None,
    resolve_fn=None,
) -> GoResolutionAttachment:
    """Resolve GO terms without allowing resolver failures to fail annotation."""
    try:
        if not has_usable_text(function, functional_category):
            return GoResolutionAttachment(
                go_terms=[],
                resolution={
                    "method": "skipped_no_text",
                    "queries": [],
                    "shortlist_size": 0,
                },
            )

        active_embedder = embedder if embedder is not None else SentenceTransformerEmbedder()
        active_resolver = resolve_fn if resolve_fn is not None else resolve_go_terms
        active_ontology_path = (
            ontology_path
            if ontology_path is not None
            else os.getenv("GO_BASIC_OBO_PATH", "data/go-basic.obo")
        )
        result = active_resolver(
            function=function,
            functional_category=functional_category,
            ontology_path=active_ontology_path,
            embedder=active_embedder,
            ranker_models=ranker_models,
        )
        terms = [
            {
                "id": term.id,
                "name": term.name,
                "aspect": term.aspect,
                **({"method": term.method} if term.method is not None else {}),
                **(
                    {"confidence": term.confidence}
                    if term.confidence is not None
                    else {}
                ),
            }
            for term in result.go_terms
        ]
        return GoResolutionAttachment(
            go_terms=terms,
            resolution={
                "method": result.method,
                "queries": list(result.queries),
                "shortlist_size": len(result.shortlist),
            },
        )
    except Exception as exc:
        return GoResolutionAttachment(
            go_terms=[],
            resolution={
                "method": "error",
                "queries": [],
                "shortlist_size": 0,
                "error": str(exc),
            },
        )
