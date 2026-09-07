"""Centralized section excerpt tier configuration from environment."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

from autoannotation.section_chunking import CHUNKING_ENV, parse_section_chunking_flag

DEFAULT_EXCERPT_MAX_CHARS: int = 6000
DEFAULT_RETRIEVAL_THRESHOLD_CHARS: int = 20_000

_ENV_EXCERPT_MAX_CHARS = "AUTOANNOTATION_SECTION_EXCERPT_MAX_CHARS"
_ENV_RETRIEVAL_THRESHOLD_CHARS = "AUTOANNOTATION_SECTION_RETRIEVAL_THRESHOLD_CHARS"


def _positive_int_from_env(
    environ: Mapping[str, str],
    key: str,
    *,
    default: int,
) -> int:
    raw = environ.get(key, "")
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    if value <= 0:
        return default
    return value


@dataclass(frozen=True)
class SectionExcerptConfig:
    chunking_enabled: bool
    max_chars: int
    retrieval_threshold_chars: int


def section_excerpt_config_from_env(
    environ: Mapping[str, str] | None = None,
) -> SectionExcerptConfig:
    if environ is None:
        environ = os.environ

    raw_chunking = environ.get(CHUNKING_ENV, "")
    if not str(raw_chunking).strip():
        chunking_enabled = True
    else:
        chunking_enabled = parse_section_chunking_flag(raw_chunking)

    max_chars = _positive_int_from_env(
        environ,
        _ENV_EXCERPT_MAX_CHARS,
        default=DEFAULT_EXCERPT_MAX_CHARS,
    )
    retrieval_threshold_chars = _positive_int_from_env(
        environ,
        _ENV_RETRIEVAL_THRESHOLD_CHARS,
        default=DEFAULT_RETRIEVAL_THRESHOLD_CHARS,
    )

    if retrieval_threshold_chars <= max_chars:
        raise ValueError(
            f"{_ENV_RETRIEVAL_THRESHOLD_CHARS}={retrieval_threshold_chars} must be "
            f"greater than {_ENV_EXCERPT_MAX_CHARS}={max_chars} "
            f"(retrieval threshold must exceed max excerpt size)"
        )

    return SectionExcerptConfig(
        chunking_enabled=chunking_enabled,
        max_chars=max_chars,
        retrieval_threshold_chars=retrieval_threshold_chars,
    )
