from autoannotation.section_chunking import (
    chunk_section_text,
    expand_section,
    expand_sections,
    excerpt_max_chars_from_env,
)


def test_under_cap_unchanged():
    text = "short paragraph"
    assert chunk_section_text(text, max_chars=100) == [text]
    assert expand_section("abstract", text, max_chars=100) == [("abstract", text)]


def test_paragraph_pack_splits_over_cap():
    p1 = "A" * 60
    p2 = "B" * 60
    text = f"{p1}\n\n{p2}"
    chunks = chunk_section_text(text, max_chars=70)
    assert chunks == [p1, p2]


def test_sentence_split_when_paragraph_too_large():
    s1 = "First sentence is long enough here."
    s2 = "Second sentence follows afterward."
    para = f"{s1} {s2}"
    assert len(para) > 40
    chunks = chunk_section_text(para, max_chars=40)
    assert all(len(c) <= 40 for c in chunks)
    assert s1 in chunks[0]


def test_expand_labels_number_when_multiple():
    p1 = "A" * 50
    p2 = "B" * 50
    out = expand_section("results", f"{p1}\n\n{p2}", max_chars=60)
    assert out == [("results#1", p1), ("results#2", p2)]


def test_excerpt_max_chars_from_env(monkeypatch):
    assert excerpt_max_chars_from_env({}) == 10_000
    assert excerpt_max_chars_from_env({"AUTOANNOTATION_SECTION_EXCERPT_MAX_CHARS": "8000"}) == 8000
