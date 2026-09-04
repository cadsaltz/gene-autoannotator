from experiments.paper.runners.tiebreak_matching import (
    is_invention,
    match_exact,
    match_soft,
)


def test_match_exact_normalizes_whitespace_case():
    assert match_exact("Apples Are Red", "apples are red")
    assert not match_exact("apples are green", "apples are red")


def test_match_soft_jaccard_threshold():
    assert match_soft(
        "apples are red and delicious",
        "apples are red and delicious",
    )
    assert match_soft(
        "red delicious apples",
        "apples are red and delicious",
    )
    assert not match_soft("completely unrelated text here", "apples are red and delicious")


def test_match_both_null():
    assert match_exact(None, None)
    assert match_soft(None, None)


def test_invention_detects_novel_string():
    cands = ["zorblin is quantex-bright", "the zorblin is quantex bright"]
    assert is_invention("photosynthesis in chloroplasts", cands)
    assert not is_invention("zorblin is quantex-bright", cands)
    assert not is_invention(None, cands)
