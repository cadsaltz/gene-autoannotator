from experiments.paper.runners.consensus_arms_claims import build_claims_for_candidate


def test_function_splits_sentences():
    claims = build_claims_for_candidate(
        {"function": "Does X. Also does Y.", "functional_category": None},
        organism="Escherichia coli",
        gene_id="b0090",
        gene_name="murG",
        model="gemma4:12b",
    )
    texts = [c["text"] for c in claims]
    assert any("Does X." in t for t in texts)
    assert any("Also does Y." in t for t in texts)
    assert all("murG" in t and "b0090" in t for t in texts)


def test_category_one_claim_per_tag():
    claims = build_claims_for_candidate(
        {"function": None, "functional_category": ["peptidoglycan biosynthesis", "cell wall"]},
        organism="Escherichia coli",
        gene_id="b0090",
        gene_name="murG",
        model="phi4:14b",
    )
    assert len(claims) == 2
    assert claims[0]["field"] == "functional_category"
