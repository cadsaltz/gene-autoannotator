"""Tiered section excerpt router: pass-through, structural chunk, or grep windows."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from autoannotation.section_chunking import expand_section
from autoannotation.section_excerpt_config import (
    SectionExcerptConfig,
    section_excerpt_config_from_env,
)
from autoannotation.section_grep_retrieval import (
    build_gene_keywords,
    grep_section_excerpts,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PreparedExcerpt:
    label: str
    text: str
    tier: str  # pass | chunk | grep | disabled


def _log_tier(label: str, text: str, tier: str, parts: int, max_chars: int) -> None:
    logger.info(
        "section=%s len=%d tier=%s parts=%d max_chars=%d",
        label,
        len(text),
        tier,
        parts,
        max_chars,
    )


def _chunk_excerpts(
    label: str,
    text: str,
    *,
    max_chars: int,
) -> list[PreparedExcerpt]:
    expanded = expand_section(label, text, max_chars=max_chars)
    return [
        PreparedExcerpt(part_label, part_text, "chunk")
        for part_label, part_text in expanded
    ]


def _grep_excerpts(
    label: str,
    text: str,
    *,
    keywords: tuple[str, ...],
    max_chars: int,
) -> list[PreparedExcerpt]:
    parts = grep_section_excerpts(text, keywords=keywords, max_chars=max_chars)
    if not parts:
        return []

    if len(parts) == 1:
        return [PreparedExcerpt(f"{label}#grep", parts[0], "grep")]

    return [
        PreparedExcerpt(f"{label}#grep{index}", part, "grep")
        for index, part in enumerate(parts, start=1)
    ]


def prepare_section_excerpts(
    label: str,
    text: str,
    *,
    gene_id: str | None,
    gene_name: str | None,
    config: SectionExcerptConfig | None = None,
    aliases: tuple[str, ...] = (),
) -> list[PreparedExcerpt]:
    cfg = config or section_excerpt_config_from_env()

    if not cfg.chunking_enabled:
        out = [PreparedExcerpt(label, text, "disabled")]
        _log_tier(label, text, "disabled", len(out), cfg.max_chars)
        return out

    if len(text) <= cfg.max_chars:
        out = [PreparedExcerpt(label, text, "pass")]
        _log_tier(label, text, "pass", len(out), cfg.max_chars)
        return out

    if len(text) < cfg.retrieval_threshold_chars:
        out = _chunk_excerpts(label, text, max_chars=cfg.max_chars)
        _log_tier(label, text, "chunk", len(out), cfg.max_chars)
        return out

    keywords = build_gene_keywords(
        gene_id or "",
        gene_name or "",
        aliases=aliases,
    )
    out = _grep_excerpts(label, text, keywords=keywords, max_chars=cfg.max_chars)
    if not out:
        logger.warning(
            "section=%s len=%d tier=grep had no keyword hits; falling back to chunk",
            label,
            len(text),
        )
        out = _chunk_excerpts(label, text, max_chars=cfg.max_chars)
        _log_tier(label, text, "chunk", len(out), cfg.max_chars)
        return out

    _log_tier(label, text, "grep", len(out), cfg.max_chars)
    return out
