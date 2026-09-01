from autoannotation.section_excerpt_config import section_excerpt_config_from_env
from autoannotation.section_excerpt_router import prepare_section_excerpts


def test_small_section_pass_tier():
    cfg = section_excerpt_config_from_env({"AUTOANNOTATION_SECTION_EXCERPT_MAX_CHARS": "6000"})
    out = prepare_section_excerpts("results", "x" * 100, gene_id="Rv1", gene_name="dnaA", config=cfg)
    assert len(out) == 1 and out[0].tier == "pass" and out[0].label == "results"


def test_medium_section_chunks():
    cfg = section_excerpt_config_from_env({
        "AUTOANNOTATION_SECTION_EXCERPT_MAX_CHARS": "60",
        "AUTOANNOTATION_SECTION_RETRIEVAL_THRESHOLD_CHARS": "10000",
    })
    text = ("A" * 60 + "\n\n") * 3  # len > max, len < retrieval
    out = prepare_section_excerpts("results", text, gene_id="Rv1", gene_name="a", config=cfg)
    assert all(p.tier == "chunk" for p in out)
    assert all(len(p.text) <= 60 for p in out)
    assert out[0].label == "results#1"


def test_large_section_uses_grep():
    cfg = section_excerpt_config_from_env({
        "AUTOANNOTATION_SECTION_EXCERPT_MAX_CHARS": "100",
        "AUTOANNOTATION_SECTION_RETRIEVAL_THRESHOLD_CHARS": "500",
    })
    text = "Z" * 600 + "Rv0001" + "Y" * 600  # len >= retrieval
    out = prepare_section_excerpts("results", text, gene_id="Rv0001", gene_name="dnaA", config=cfg)
    assert out[0].tier == "grep"
    assert "Rv0001" in out[0].text
    assert len(out[0].text) <= 100


def test_large_section_falls_back_to_chunk_when_no_gene_hits():
    cfg = section_excerpt_config_from_env({
        "AUTOANNOTATION_SECTION_EXCERPT_MAX_CHARS": "200",
        "AUTOANNOTATION_SECTION_RETRIEVAL_THRESHOLD_CHARS": "500",
    })
    out = prepare_section_excerpts("results", "Z" * 600, gene_id="Rv0001", gene_name="dnaA", config=cfg)
    assert all(p.tier == "chunk" for p in out)
