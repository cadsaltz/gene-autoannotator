"""Arm C: excerpt-aware verbatim consensus judge (experiment-only).

Unlike production consensus, the judge sees the source excerpt and the target
gene, receives every candidate (no vote gate), and must pick values verbatim.
A post-filter (``select_supported_verbatim``) drops anything that is not
supported by a candidate, so the judge cannot invent wording.
"""

from __future__ import annotations

import json
from typing import Any, Callable

from autoannotation.consensus import token_jaccard
from autoannotation.llms import (
    _batch_consensus_schema,
    chat_response_content,
    ollama_chat,
    parse_response_json,
)

JUDGE_MODEL = "gemma4:26b"
SOFT_STRING_JACCARD = 0.85

ARM_C_JUDGE_PROMPT = """
You are the consensus judge for gene annotation candidates extracted by different models
from the same paper excerpt.

Target gene: {gene_name} ({gene_id})

Excerpt:
{excerpt}

Candidate objects (different extractor models; null means that model reported nothing):
{candidates_json}

Using ONLY the excerpt and the candidate values, for each field select the candidate value
that the excerpt supports about gene {gene_name} ({gene_id}), or null.

Fields: {field_list}

Rules:
- Return JSON with exactly the listed field keys.
- Select a value VERBATIM from one of the candidates. Do not rewrite or invent wording.
- If multiple candidates are supported, prefer the one that best matches the excerpt; if tied, prefer the shorter value.
- Use null when the excerpt does not support any candidate for that field about this gene.
- Ignore candidates that attribute another gene's facts to this gene.
"""


def build_arm_c_prompt(
    *,
    gene_id: str | None,
    gene_name: str,
    excerpt: str | None,
    candidates: list[dict[str, Any]],
    field_keys: list[str],
) -> str:
    payload = [{key: cand.get(key) for key in field_keys} for cand in candidates]
    return ARM_C_JUDGE_PROMPT.format(
        gene_name=gene_name,
        gene_id=gene_id or "unknown",
        excerpt=excerpt or "",
        candidates_json=json.dumps(payload, indent=2),
        field_list=", ".join(field_keys),
    )


def _match_candidate_value(value: Any, candidate_values: list[Any]) -> Any:
    """Return the candidate value supporting ``value`` or None.

    Strings: exact, else token Jaccard >= 0.85 (candidate wording is returned).
    Arrays: set-equal (order-insensitive) to a candidate array.
    Booleans: exact bool equality (``1``/``"true"`` never match).
    """
    if value is None:
        return None
    if isinstance(value, bool):
        for cand in candidate_values:
            if isinstance(cand, bool) and cand is value:
                return cand
        return None
    if isinstance(value, str):
        if not value.strip():
            return None
        strings = [c for c in candidate_values if isinstance(c, str) and c.strip()]
        for cand in strings:
            if cand == value:
                return cand
        best, best_score = None, SOFT_STRING_JACCARD
        for cand in strings:
            score = token_jaccard(value, cand)
            if score >= best_score:
                best, best_score = cand, score
        return best
    if isinstance(value, list):
        if not value:
            return None
        try:
            target = set(value)
        except TypeError:
            return None
        for cand in candidate_values:
            if isinstance(cand, list) and cand:
                try:
                    if set(cand) == target:
                        return list(cand)
                except TypeError:
                    continue
        return None
    return None


def select_supported_verbatim(
    judge_payload: dict[str, Any] | None,
    candidates: list[dict[str, Any]],
    field_keys: list[str],
) -> dict[str, Any]:
    """Keep only judge values that are supported by some candidate."""
    payload = judge_payload or {}
    out: dict[str, Any] = {}
    for key in field_keys:
        candidate_values = [c.get(key) for c in candidates]
        out[key] = _match_candidate_value(payload.get(key), candidate_values)
    return out


def make_ollama_judge_fn(
    *,
    model: str = JUDGE_MODEL,
    organism_profile=None,
    field_defs_profile=None,
) -> Callable[..., dict[str, Any]]:
    """Thin live wiring: returns a ``judge_fn`` that calls Ollama (for Task 8)."""

    def judge_fn(
        *,
        candidates: list[dict[str, Any]],
        field_keys: list[str],
        excerpt: str | None,
        gene_id: str | None,
        gene_name: str,
    ) -> dict[str, Any]:
        prompt = build_arm_c_prompt(
            gene_id=gene_id,
            gene_name=gene_name,
            excerpt=excerpt,
            candidates=candidates,
            field_keys=field_keys,
        )
        schema = _batch_consensus_schema(
            list(field_keys),
            field_defs_profile=field_defs_profile,
            organism_profile=organism_profile,
        )
        response = ollama_chat(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            json_schema=schema,
            role="section_consensus",
            think=False,
        )
        payload = parse_response_json(
            chat_response_content(response, role="section_consensus", model=model),
            role="section_consensus",
            model=model,
        )
        return {key: payload.get(key) for key in field_keys}

    return judge_fn
