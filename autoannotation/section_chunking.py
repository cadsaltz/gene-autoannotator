"""Deterministic section excerpt chunking before LLM extraction."""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Mapping

DEFAULT_EXCERPT_MAX_CHARS: int = 10_000

CHUNKING_ENV = "AUTOANNOTATION_SECTION_CHUNKING"
_TRUTHY = frozenset({"1", "true", "yes", "on"})
_FALSY = frozenset({"0", "false", "no", "off"})

_ENV_EXCERPT_MAX_CHARS = "AUTOANNOTATION_SECTION_EXCERPT_MAX_CHARS"

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])(?:\s+|$)")


def excerpt_max_chars_from_env(environ: Mapping[str, str] | None = None) -> int:
    if environ is None:
        environ = os.environ
    raw = environ.get(_ENV_EXCERPT_MAX_CHARS, "")
    if not raw:
        return DEFAULT_EXCERPT_MAX_CHARS
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_EXCERPT_MAX_CHARS
    if value <= 0:
        return DEFAULT_EXCERPT_MAX_CHARS
    return value


def parse_section_chunking_flag(raw: str) -> bool:
    normalized = str(raw).strip().lower()
    if normalized in _TRUTHY:
        return True
    if normalized in _FALSY:
        return False
    raise ValueError(
        f"Invalid {CHUNKING_ENV}={raw!r}; expected one of "
        f"{sorted(_TRUTHY | _FALSY)}"
    )


def section_chunking_enabled(*, environ: Mapping[str, str] | None = None) -> bool:
    if environ is None:
        environ = os.environ
    raw = environ.get(CHUNKING_ENV, "")
    if not str(raw).strip():
        return True
    return parse_section_chunking_flag(raw)


def split_paragraphs(text: str) -> list[str]:
    parts = re.split(r"\n\s*\n", text)
    return [part.strip() for part in parts if part.strip()]


def split_sentences(text: str) -> list[str]:
    parts = _SENTENCE_SPLIT_RE.split(text.strip())
    return [part.strip() for part in parts if part.strip()]


def pack_units(units: list[str], *, max_chars: int, joiner: str) -> list[str]:
    if not units:
        return []
    chunks: list[str] = []
    current = units[0]
    for unit in units[1:]:
        extra = len(joiner) if current else 0
        if len(current) + extra + len(unit) <= max_chars:
            current = f"{current}{joiner}{unit}"
        else:
            chunks.append(current)
            current = unit
    chunks.append(current)
    return chunks


def chunk_section_text(text: str, *, max_chars: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]

    paragraphs = split_paragraphs(text)
    packed = pack_units(paragraphs, max_chars=max_chars, joiner="\n\n")

    chunks: list[str] = []
    for piece in packed:
        if len(piece) <= max_chars:
            chunks.append(piece)
            continue
        sentences = split_sentences(piece)
        for sentence_chunk in pack_units(sentences, max_chars=max_chars, joiner=" "):
            if len(sentence_chunk) <= max_chars:
                chunks.append(sentence_chunk)
            else:
                logging.warning(
                    "Section excerpt sentence exceeds max_chars=%d; hard-truncating",
                    max_chars,
                )
                chunks.append(sentence_chunk[:max_chars])
    return chunks


def expand_section(
    label: str, text: str, *, max_chars: int
) -> list[tuple[str, str]]:
    chunks = chunk_section_text(text, max_chars=max_chars)
    if len(chunks) == 1:
        return [(label, chunks[0])]
    return [(f"{label}#{index}", chunk) for index, chunk in enumerate(chunks, start=1)]


def expand_sections(
    sections: list[tuple[str, str]], *, max_chars: int
) -> list[tuple[str, str]]:
    expanded: list[tuple[str, str]] = []
    for label, text in sections:
        expanded.extend(expand_section(label, text, max_chars=max_chars))
    return expanded
