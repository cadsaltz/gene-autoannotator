from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from goresolve import has_usable_text, resolve_go_terms
from goresolve.embeddings import SentenceTransformerEmbedder
from goresolve.rank import GO_RANK_JSON_SCHEMA

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class GoResolutionAttachment:
    go_terms: list[dict]
    resolution: dict


def is_go_resolution_enabled(profile) -> bool:
    return bool(getattr(profile, "go_resolution_enabled", False))


def _router_rank_fn(prompt: str, model: str) -> dict:
    """Rank GO candidates through the worker's Ollama router.

    Unlike ``goresolve.rank.ollama_rank_fn`` (bare ``ollama.chat``, used only
    by the standalone ``python -m goresolve`` CLI), the annotation pipeline
    must route every LLM call through ``autoannotation.llms.ollama_chat`` so
    ranking requests share the worker router's queueing, keep-alive, and
    job/role tracking with the rest of the pipeline.
    """
    from . import llms

    response = llms.ollama_chat(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        json_schema=GO_RANK_JSON_SCHEMA,
        role="go_ranking",
    )
    content = llms.chat_response_content(response, role="go_ranking", model=model)
    return llms.parse_response_json(content, role="go_ranking", model=model)


def _ontology_path_error(ontology_path) -> str | None:
    if not ontology_path or not os.path.isfile(ontology_path):
        return f"GO ontology file not found: {ontology_path!r}"
    if os.path.getsize(ontology_path) == 0:
        return f"GO ontology file is empty: {ontology_path!r}"
    return None


def resolve_for_annotation(
    *,
    function,
    functional_category,
    ranker_models: list[str],
    ontology_path: str | None = None,
    embedder=None,
    resolve_fn=None,
    rank_fn=None,
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

        active_ontology_path = (
            ontology_path
            if ontology_path is not None
            else os.getenv("GO_BASIC_OBO_PATH", "data/go-basic.obo")
        )

        # Only the default resolver actually loads the OBO file from disk; a
        # caller-supplied resolve_fn owns its own ontology handling. Without
        # this check, a missing/empty OBO silently loads an empty ontology
        # and resolve_go_terms reports the misleading "no_candidates".
        if resolve_fn is None:
            ontology_error = _ontology_path_error(active_ontology_path)
            if ontology_error is not None:
                log.warning("GO resolution skipped: %s", ontology_error)
                return GoResolutionAttachment(
                    go_terms=[],
                    resolution={
                        "method": "error",
                        "queries": [],
                        "shortlist_size": 0,
                        "error": ontology_error,
                    },
                )

        active_embedder = embedder if embedder is not None else SentenceTransformerEmbedder()
        active_resolver = resolve_fn if resolve_fn is not None else resolve_go_terms
        active_rank_fn = rank_fn if rank_fn is not None else _router_rank_fn
        result = active_resolver(
            function=function,
            functional_category=functional_category,
            ontology_path=active_ontology_path,
            embedder=active_embedder,
            ranker_models=ranker_models,
            rank_fn=active_rank_fn,
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
        message = str(exc).strip() or exc.__class__.__name__
        log.warning("GO resolution failed: %s", message, exc_info=True)
        return GoResolutionAttachment(
            go_terms=[],
            resolution={
                "method": "error",
                "queries": [],
                "shortlist_size": 0,
                "error": message,
            },
        )
