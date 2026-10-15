from __future__ import annotations

import copy
from typing import Any, Callable

from autoannotation.consensus import hybrid_section_consensus

TRIO_B = ("gemma4:12b", "phi4:14b", "dolphin3:8b")
TRIO_BREF = ("gemma4:12b", "phi4:14b", "granite4.2:8b")
JUDGE_MODEL = "gemma4:26b"


def decide_arm_a(by_model: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Arm A: gemma4:12b output passed through unchanged (deep copy)."""
    return copy.deepcopy(by_model["gemma4:12b"])


def make_production_batch_merger(
    llm_handler,
    *,
    model: str = JUDGE_MODEL,
    organism_profile=None,
    field_defs_profile=None,
) -> Callable[[list[dict[str, Any]], list[str]], dict[str, Any]]:
    """Build a production-style batch_merger around an LLMHandler.

    Delegates to ``LLMHandler._ollama_batch_consensus_merge`` which formats the
    unchanged production ``BATCH_CONSENSUS_PROMPT`` (candidates + field list
    only; no excerpt) and calls Ollama with ``model`` (default: gemma4:26b).
    """

    def batch_merger(
        candidates: list[dict[str, Any]],
        unresolved_fields: list[str],
    ) -> dict[str, Any]:
        result, _duration_sec = llm_handler._ollama_batch_consensus_merge(
            candidates,
            unresolved_fields,
            model=model,
            organism_profile=organism_profile,
            field_defs_profile=field_defs_profile,
        )
        return {key: result.get(key) for key in unresolved_fields}

    return batch_merger


def decide_arm_b(
    by_model: dict[str, dict[str, Any]],
    *,
    models: tuple[str, ...],
    batch_merger: Callable,
    expected_gene_id: str | None,
    expected_name: str,
    organism_profile,
    field_defs_profile,
    excerpt: str | None,
) -> tuple[dict[str, Any], dict[str, str], int]:
    """Arm B: production hybrid consensus over a trio of candidates.

    The excerpt is only used by the post-merge word-overlap validator, as in
    production; it is not part of the merger prompt.
    """
    candidates = [by_model[m] for m in models]
    return hybrid_section_consensus(
        candidates,
        excerpt=excerpt,
        expected_gene_id=expected_gene_id,
        expected_name=expected_name,
        organism_profile=organism_profile,
        field_defs_profile=field_defs_profile,
        batch_merger=batch_merger,
    )
