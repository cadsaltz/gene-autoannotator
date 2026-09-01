"""Gene-centric grep window retrieval for large section excerpts."""

from __future__ import annotations

import re

GREP_MERGE_GAP_CHARS = 200
GREP_PREAMBLE_ENABLED = True
_PREAMBLE_HALF_CHARS = 250


def _window_half_chars(max_chars: int) -> int:
    return min(1000, max_chars // 2)


def build_gene_keywords(
    gene_id: str,
    gene_name: str,
    aliases: tuple[str, ...] = (),
) -> tuple[str, ...]:
    seen_lower: set[str] = set()
    keywords: list[str] = []
    for raw in (gene_id, gene_name, *aliases):
        if raw is None:
            continue
        keyword = str(raw).strip()
        if not keyword:
            continue
        lower = keyword.lower()
        if lower in seen_lower:
            continue
        seen_lower.add(lower)
        keywords.append(keyword)
    keywords.sort(key=len, reverse=True)
    return tuple(keywords)


def _keyword_pattern(keyword: str) -> re.Pattern[str]:
    return re.compile(re.escape(keyword), re.IGNORECASE)


def _find_match_spans(text: str, keywords: tuple[str, ...]) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    for keyword in sorted(keywords, key=len, reverse=True):
        for match in _keyword_pattern(keyword).finditer(text):
            spans.append((match.start(), match.end()))
    if not spans:
        return []
    spans.sort()
    deduped: list[tuple[int, int]] = [spans[0]]
    for start, end in spans[1:]:
        prev_start, prev_end = deduped[-1]
        if start == prev_start and end == prev_end:
            continue
        deduped.append((start, end))
    return deduped


def _build_intervals(
    spans: list[tuple[int, int]],
    text_len: int,
    *,
    half: int,
) -> list[tuple[int, int]]:
    return [
        (max(0, start - half), min(text_len, end + half))
        for start, end in spans
    ]


def _merge_intervals(
    intervals: list[tuple[int, int]],
    *,
    merge_gap: int,
) -> list[tuple[int, int]]:
    if not intervals:
        return []
    merged = [intervals[0]]
    for start, end in intervals[1:]:
        prev_start, prev_end = merged[-1]
        if start - prev_end <= merge_gap:
            merged[-1] = (prev_start, max(prev_end, end))
        else:
            merged.append((start, end))
    return merged


def _hit_positions_in_interval(
    spans: list[tuple[int, int]],
    start: int,
    end: int,
) -> list[int]:
    positions: list[int] = []
    for match_start, match_end in spans:
        if match_end <= start or match_start >= end:
            continue
        positions.append(match_start)
    return positions


def _trim_excerpt(
    text: str,
    start: int,
    end: int,
    *,
    max_chars: int,
    hit_positions: list[int],
) -> str:
    excerpt = text[start:end]
    if len(excerpt) <= max_chars:
        return excerpt

    if hit_positions:
        rel_hits = [pos - start for pos in hit_positions]
        center = sum(rel_hits) // len(rel_hits)
        window_start = max(0, center - max_chars // 2)
        if window_start + max_chars > len(excerpt):
            window_start = max(0, len(excerpt) - max_chars)
        return excerpt[window_start : window_start + max_chars]

    return excerpt[:max_chars]


def _first_mention_snippet(text: str, keywords: tuple[str, ...]) -> str:
    earliest: tuple[int, int] | None = None
    for keyword in sorted(keywords, key=len, reverse=True):
        match = _keyword_pattern(keyword).search(text)
        if match is None:
            continue
        if earliest is None or match.start() < earliest[0]:
            earliest = (match.start(), match.end())
    if earliest is None:
        return ""
    start, end = earliest
    snippet_start = max(0, start - _PREAMBLE_HALF_CHARS)
    snippet_end = min(len(text), end + _PREAMBLE_HALF_CHARS)
    return text[snippet_start:snippet_end]


def _apply_preamble(
    parts: list[str],
    text: str,
    keywords: tuple[str, ...],
    *,
    max_chars: int,
) -> list[str]:
    if not GREP_PREAMBLE_ENABLED or not parts:
        return parts

    preamble = _first_mention_snippet(text, keywords)
    if not preamble:
        return parts

    first = parts[0]
    if first.startswith(preamble) or preamble.startswith(first):
        return parts

    prefix_len = min(len(preamble), 40)
    if first.startswith(preamble[:prefix_len]):
        return parts

    combined = f"{preamble}\n\n...\n\n{first}"
    if len(combined) <= max_chars:
        parts[0] = combined
        return parts

    parts[0] = combined[:max_chars]
    return parts


def grep_section_excerpts(
    text: str,
    *,
    keywords: tuple[str, ...],
    max_chars: int,
) -> list[str]:
    if not text or not keywords:
        return []

    spans = _find_match_spans(text, keywords)
    if not spans:
        return []

    half = _window_half_chars(max_chars)
    intervals = _build_intervals(spans, len(text), half=half)
    intervals.sort()
    merged = _merge_intervals(intervals, merge_gap=GREP_MERGE_GAP_CHARS)

    parts: list[str] = []
    for start, end in merged:
        hits = _hit_positions_in_interval(spans, start, end)
        parts.append(
            _trim_excerpt(
                text,
                start,
                end,
                max_chars=max_chars,
                hit_positions=hits,
            )
        )

    return _apply_preamble(parts, text, keywords, max_chars=max_chars)
