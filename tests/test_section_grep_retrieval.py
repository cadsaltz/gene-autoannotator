from autoannotation.section_grep_retrieval import grep_section_excerpts


def test_grep_finds_windows_and_merges_overlap():
    text = "A" * 500 + "Rv0001" + "B" * 100 + "rv0001" + "C" * 500
    parts = grep_section_excerpts(text, keywords=("Rv0001",), max_chars=8000)
    assert len(parts) == 1
    assert "Rv0001" in parts[0]
    assert len(parts[0]) <= 8000


def test_no_hits_returns_empty():
    assert grep_section_excerpts("no gene here", keywords=("Rv0001",), max_chars=6000) == []


def test_each_part_respects_max_chars():
    text = "Z" * 3000 + "Rv0001" + "Y" * 3000 + "Rv0001" + "X" * 3000
    parts = grep_section_excerpts(text, keywords=("Rv0001",), max_chars=500)
    assert parts
    assert all(len(p) <= 500 for p in parts)


def test_preamble_prepends_first_mention():
    text = "Intro Rv0001 defined here. " + "X" * 5000 + " Later Rv0001 again."
    parts = grep_section_excerpts(text, keywords=("Rv0001",), max_chars=6000)
    assert parts[0].startswith("Intro Rv0001")
