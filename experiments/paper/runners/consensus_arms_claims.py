from __future__ import annotations

from typing import Any, TypedDict

from autoannotation.section_chunking import split_sentences
from experiments.paper.runners.common import BIOLOGY_FIELDS, is_nullish


class Claim(TypedDict):
    field: str
    text: str
    source_model: str
    source_value: Any
    claim_index: int


def _prefix(*, organism: str, gene_id: str, gene_name: str) -> str:
    return f"In {organism}, gene {gene_name} ({gene_id})"


def build_claims_for_candidate(
    output: dict[str, Any],
    *,
    organism: str,
    gene_id: str,
    gene_name: str,
    model: str,
) -> list[Claim]:
    prefix = _prefix(organism=organism, gene_id=gene_id, gene_name=gene_name)
    claims: list[Claim] = []
    claim_index = 0

    for field in BIOLOGY_FIELDS:
        value = output.get(field)
        if is_nullish(value):
            continue

        if field == "function":
            for sentence in split_sentences(str(value)):
                if not sentence.strip():
                    continue
                claims.append(
                    {
                        "field": field,
                        "text": f"{prefix}: {sentence}",
                        "source_model": model,
                        "source_value": sentence,
                        "claim_index": claim_index,
                    }
                )
                claim_index += 1
            continue

        if field == "functional_category":
            tags = value if isinstance(value, list) else [value]
            for tag in tags:
                tag_text = str(tag).strip()
                if not tag_text or is_nullish(tag_text):
                    continue
                claims.append(
                    {
                        "field": field,
                        "text": f"{prefix} is involved in {tag_text}.",
                        "source_model": model,
                        "source_value": tag_text,
                        "claim_index": claim_index,
                    }
                )
                claim_index += 1
            continue

        if field == "drug_susc_impact":
            text = f"{prefix} drug susceptibility impact: {value}"
            claims.append(
                {
                    "field": field,
                    "text": text,
                    "source_model": model,
                    "source_value": value,
                    "claim_index": claim_index,
                }
            )
            claim_index += 1
            continue

        if field == "infection_impact":
            text = f"{prefix} infection impact: {value}"
            claims.append(
                {
                    "field": field,
                    "text": text,
                    "source_model": model,
                    "source_value": value,
                    "claim_index": claim_index,
                }
            )
            claim_index += 1
            continue

        if field == "essential_in_vitro":
            essential = "essential" if value else "not essential"
            claims.append(
                {
                    "field": field,
                    "text": f"{prefix} is {essential} in vitro.",
                    "source_model": model,
                    "source_value": value,
                    "claim_index": claim_index,
                }
            )
            claim_index += 1
            continue

        if field == "essential_in_vivo":
            essential = "essential" if value else "not essential"
            claims.append(
                {
                    "field": field,
                    "text": f"{prefix} is {essential} in vivo.",
                    "source_model": model,
                    "source_value": value,
                    "claim_index": claim_index,
                }
            )
            claim_index += 1

    return claims


def build_claims_for_trio(
    by_model: dict[str, dict[str, Any]],
    models: tuple[str, ...] | list[str],
    **meta: Any,
) -> list[Claim]:
    claims: list[Claim] = []
    for model in models:
        output = by_model.get(model, {})
        for claim in build_claims_for_candidate(output, model=model, **meta):
            claim = dict(claim)
            claim["claim_index"] = len(claims)
            claims.append(claim)  # type: ignore[arg-type]
    return claims
