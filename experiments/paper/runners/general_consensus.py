"""Candidate-only consensus mergers for paper tie-break experiments."""

from __future__ import annotations

import json
from typing import Any

from autoannotation.consensus import BatchMerger, FieldSpec
from autoannotation.llms import (
    chat_response_content,
    ollama_chat,
    parse_response_json,
)

GENERAL_FIELD_SPECS = (FieldSpec("answer", "string"),)

GENERAL_BATCH_CONSENSUS_PROMPT = """
You merge candidate answers from different extractor models.

Candidate objects:
{candidates_json}

Merge ONLY these fields: {field_list}

Return JSON with exactly those keys. Use null for any field you cannot
reconcile from the candidates.

Rules:
- Reconcile only from the candidate values provided. You do not have access to
  the source text.
- When candidates agree exactly or as paraphrases, return concise wording drawn
  from those candidates.
- Prefer a value supported by a clear majority.
- Do not invent or add facts absent from every candidate.
- Return null for irreconcilable conflicts with no clear majority.
"""


def _general_batch_schema(unresolved_fields: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            field_key: {"type": ["string", "null"]}
            for field_key in unresolved_fields
        },
        "required": unresolved_fields,
        "additionalProperties": False,
    }


def make_general_batch_merger(model: str) -> BatchMerger:
    """Build an Ollama-backed merger for general string fields."""

    def batch_merger(
        candidates: list[dict[str, Any]],
        unresolved_fields: list[str],
    ) -> dict[str, Any]:
        candidate_payload = [
            {
                field_key: candidate.get(field_key)
                for field_key in unresolved_fields
            }
            for candidate in candidates
        ]
        prompt = GENERAL_BATCH_CONSENSUS_PROMPT.format(
            candidates_json=json.dumps(candidate_payload, indent=2),
            field_list=", ".join(unresolved_fields),
        )
        response = ollama_chat(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            json_schema=_general_batch_schema(unresolved_fields),
            role="section_consensus",
        )
        payload = parse_response_json(
            chat_response_content(
                response,
                role="section_consensus",
                model=model,
            ),
            role="section_consensus",
            model=model,
        )
        return {
            field_key: payload.get(field_key)
            for field_key in unresolved_fields
        }

    return batch_merger


def make_biology_batch_merger(llm_handler) -> BatchMerger:
    """Adapt the existing biology handler to the runner's merger interface."""
    model = getattr(llm_handler, "consensus_model", "qwen3:8b")

    def batch_merger(
        candidates: list[dict[str, Any]],
        unresolved_fields: list[str],
    ) -> dict[str, Any]:
        result, _duration_sec = llm_handler._ollama_batch_consensus_merge(
            candidates,
            unresolved_fields,
            model=model,
        )
        return {
            field_key: result.get(field_key)
            for field_key in unresolved_fields
        }

    return batch_merger
