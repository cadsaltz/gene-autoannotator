from autoannotation.section_grep_retrieval import (
    _window_half_chars,
    grep_section_excerpts,
)


def test_window_half_is_one_third_of_max():
    assert _window_half_chars(6000) == 2000
    assert _window_half_chars(5000) == 1666
    assert _window_half_chars(3) == 1


def test_grep_finds_windows_and_merges_overlap():
    text = "A" * 500 + "Rv0001" + "B" * 100 + "rv0001" + "C" * 500
    parts = grep_section_excerpts(text, keywords=("Rv0001",), max_chars=8000)
    assert len(parts) == 1
    assert "Rv0001" in parts[0]
    assert len(parts[0]) <= 8000


def test_same_sentence_hits_merge_into_one_excerpt():
    """Two hits in one sentence must not produce near-duplicate excerpts."""
    text = (
        "Prefix padding. " * 40
        + "The locus Rv0001 (also called rv0001) initiates replication. "
        + "Suffix padding. " * 40
    )
    parts = grep_section_excerpts(text, keywords=("Rv0001",), max_chars=6000)
    assert len(parts) == 1
    assert parts[0].lower().count("rv0001") >= 2
    assert len(parts[0]) <= 6000


def test_distant_hits_remain_separate_when_beyond_merge_gap():
    # half = 6000//3 = 2000; gap >> merge_gap (200) and windows must not overlap
    text = "A" * 3000 + "Rv0001" + "B" * 5000 + "Rv0001" + "C" * 3000
    parts = grep_section_excerpts(text, keywords=("Rv0001",), max_chars=6000)
    assert len(parts) == 2
    assert all(len(part) <= 6000 for part in parts)


def test_no_hits_returns_empty():
    assert grep_section_excerpts("no gene here", keywords=("Rv0001",), max_chars=6000) == []


def test_each_part_respects_max_chars():
    text = "Z" * 3000 + "Rv0001" + "Y" * 3000 + "Rv0001" + "X" * 3000
    parts = grep_section_excerpts(text, keywords=("Rv0001",), max_chars=500)
    assert parts
    assert all(len(p) <= 500 for p in parts)


def test_isolated_hit_window_uses_third_max_each_side():
    max_chars = 6000
    half = max_chars // 3
    text = "Z" * 10000 + "Rv0001" + "Y" * 10000
    parts = grep_section_excerpts(text, keywords=("Rv0001",), max_chars=max_chars)
    assert len(parts) == 1
    # Single hit → roughly 2*half + keyword, well under max
    assert half <= len(parts[0]) <= 2 * half + len("Rv0001") + 50
    assert "Rv0001" in parts[0]


def test_preamble_prepends_first_mention():
    text = "Intro Rv0001 defined here. " + "X" * 5000 + " Later Rv0001 again."
    parts = grep_section_excerpts(text, keywords=("Rv0001",), max_chars=6000)
    assert parts[0].startswith("Intro Rv0001")
