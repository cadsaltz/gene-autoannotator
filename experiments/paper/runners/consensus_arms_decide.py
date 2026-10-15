from __future__ import annotations

import copy
from typing import Any, Callable

from autoannotation.consensus import hybrid_section_consensus
from experiments.paper.runners.common import BIOLOGY_FIELDS
from experiments.paper.runners.consensus_arms_judge_c import (
    JUDGE_MODEL,
    select_supported_verbatim,
)

TRIO_B = ("gemma4:12b", "phi4:14b", "dolphin3:8b")
TRIO_BREF = ("gemma4:12b", "phi4:14b", "granite4.2:8b")


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


def decide_arm_c(
    by_model: dict[str, dict[str, Any]],
    *,
    models: tuple[str, ...],
    judge_fn: Callable[..., dict[str, Any]],
    expected_gene_id: str | None,
    expected_name: str,
    excerpt: str | None,
    field_keys: list[str],
) -> dict[str, Any]:
    """Arm C: excerpt-aware verbatim judge over ALL trio candidates.

    No vote gate: every candidate (including null-filled ones) is sent to the
    judge. The judge's per-field selections are post-filtered so only values
    supported by a candidate survive; inventions become None.
    """
    candidates = [copy.deepcopy(by_model[m]) for m in models]
    payload = judge_fn(
        candidates=candidates,
        field_keys=list(field_keys),
        excerpt=excerpt,
        gene_id=expected_gene_id,
        gene_name=expected_name,
    )
    return select_supported_verbatim(payload, candidates, list(field_keys))


def _dedupe(items: list[Any]) -> list[Any]:
    seen: set[Any] = set()
    out: list[Any] = []
    for item in items:
        key = str(item)
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def decide_arm_d(
    by_model: dict[str, dict[str, Any]],
    *,
    models: tuple[str, ...],
    claims: list[dict[str, Any]],
    scores_by_claim_id: dict[int, float],
    threshold: float,
) -> dict[str, Any]:
    """Arm D: keep only claim pieces whose classifier score >= threshold.

    ``claims`` come from ``build_claims_for_trio`` (global ``claim_index``);
    ``scores_by_claim_id`` maps ``claim_index`` to a support score. Fields are
    reassembled from surviving pieces:

    - function / drug_susc_impact / infection_impact: kept pieces joined by a
      space (exact duplicates dropped)
    - functional_category: list of kept tags (duplicates dropped)
    - essential_in_vitro / essential_in_vivo: strict majority of kept bool
      claims; a tie yields None

    A field with no passing claims is None. ``by_model`` is accepted for
    interface symmetry with the other arms; output is built only from claims.
    """
    allowed = set(models)
    kept: dict[str, list[Any]] = {field: [] for field in BIOLOGY_FIELDS}
    for claim in claims:
        if claim["source_model"] not in allowed:
            continue
        score = scores_by_claim_id.get(claim["claim_index"])
        if score is None or score < threshold:
            continue
        if claim["field"] in kept:
            kept[claim["field"]].append(claim["source_value"])

    result: dict[str, Any] = {}
    for field in BIOLOGY_FIELDS:
        values = kept[field]
        if not values:
            result[field] = None
        elif field == "functional_category":
            result[field] = _dedupe(values)
        elif field in ("essential_in_vitro", "essential_in_vivo"):
            yes = sum(1 for v in values if bool(v))
            no = len(values) - yes
            result[field] = True if yes > no else False if no > yes else None
        else:
            result[field] = " ".join(str(v) for v in _dedupe(values))
    return result
