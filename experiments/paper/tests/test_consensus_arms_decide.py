from experiments.paper.runners.consensus_arms_decide import (
    JUDGE_MODEL,
    TRIO_B,
    TRIO_BREF,
    decide_arm_a,
    decide_arm_b,
    decide_arm_c,
    decide_arm_d,
    make_production_batch_merger,
)


def test_arm_a_is_gemma_passthrough():
    by_model = {
        "gemma4:12b": {"function": "real", "functional_category": None},
        "dolphin3:8b": {"function": "hallucination", "functional_category": None},
    }
    out = decide_arm_a(by_model)
    assert out == by_model["gemma4:12b"]
    assert out is not by_model["gemma4:12b"]  # copy


def test_arm_b_calls_hybrid_with_trio_candidates(monkeypatch):
    calls = {}

    def fake_hybrid(candidates, **kwargs):
        calls["candidates"] = candidates
        calls["kwargs"] = kwargs
        return {"function": "merged"}, {"function": "majority"}, 1

    monkeypatch.setattr(
        "experiments.paper.runners.consensus_arms_decide.hybrid_section_consensus",
        fake_hybrid,
    )
    by_model = {
        "gemma4:12b": {"function": "a", "name": "murG"},
        "phi4:14b": {"function": "b", "name": "murG"},
        "dolphin3:8b": {"function": "c", "name": "murG"},
        "granite4.2:8b": {"function": "should-not-appear", "name": "murG"},
    }
    merger = lambda *_: {}
    merged, prov, n = decide_arm_b(
        by_model,
        models=TRIO_B,
        batch_merger=merger,
        expected_gene_id="b0090",
        expected_name="murG",
        organism_profile=None,
        field_defs_profile=None,
        excerpt="excerpt text",
    )
    assert [c["function"] for c in calls["candidates"]] == ["a", "b", "c"]
    assert calls["kwargs"]["excerpt"] == "excerpt text"
    assert calls["kwargs"]["batch_merger"] is merger
    assert calls["kwargs"]["expected_gene_id"] == "b0090"
    assert calls["kwargs"]["expected_name"] == "murG"
    assert merged["function"] == "merged"
    assert prov == {"function": "majority"}
    assert n == 1


def test_trio_constants():
    assert TRIO_B == ("gemma4:12b", "phi4:14b", "dolphin3:8b")
    assert TRIO_BREF == ("gemma4:12b", "phi4:14b", "granite4.2:8b")
    assert JUDGE_MODEL == "gemma4:26b"


def test_production_batch_merger_wraps_handler_with_judge_model():
    seen = {}

    class FakeHandler:
        def _ollama_batch_consensus_merge(
            self,
            candidates,
            unresolved_fields,
            *,
            model,
            organism_profile=None,
            field_defs_profile=None,
        ):
            seen.update(
                candidates=candidates,
                fields=unresolved_fields,
                model=model,
                organism_profile=organism_profile,
                field_defs_profile=field_defs_profile,
            )
            return {"function": "m", "extra": "dropped"}, 0.5

    merger = make_production_batch_merger(
        FakeHandler(), organism_profile="org", field_defs_profile="defs"
    )
    out = merger([{"function": "x"}, {"function": "y"}], ["function"])
    assert out == {"function": "m"}
    assert seen["model"] == JUDGE_MODEL
    assert seen["fields"] == ["function"]
    assert seen["organism_profile"] == "org"
    assert seen["field_defs_profile"] == "defs"


def test_arm_c_no_vote_gate_sends_all_candidates():
    seen = {}

    def judge_fn(candidates, field_keys, excerpt, gene_id, gene_name):
        seen.update(
            n=len(candidates),
            candidates=candidates,
            excerpt=excerpt,
            gene_id=gene_id,
            gene_name=gene_name,
        )
        return {k: candidates[0].get(k) for k in field_keys}

    by_model = {
        "gemma4:12b": {"function": "a"},
        "phi4:14b": {"function": None},
        "dolphin3:8b": {"function": "c"},
        "granite4.2:8b": {"function": "not-in-trio"},
    }
    out = decide_arm_c(
        by_model,
        models=TRIO_B,
        judge_fn=judge_fn,
        expected_gene_id="b0090",
        expected_name="murG",
        excerpt="text",
        field_keys=["function"],
    )
    assert seen["n"] == 3
    assert [c["function"] for c in seen["candidates"]] == ["a", None, "c"]
    assert seen["excerpt"] == "text"
    assert seen["gene_id"] == "b0090" and seen["gene_name"] == "murG"
    assert out == {"function": "a"}


def test_arm_c_filters_invented_judge_values():
    def judge_fn(candidates, field_keys, excerpt, gene_id, gene_name):
        return {"function": "totally invented wording", "cats": ["x", "y"]}

    by_model = {
        "gemma4:12b": {"function": "real function text", "cats": ["x"]},
        "phi4:14b": {"function": None, "cats": None},
        "dolphin3:8b": {"function": "other", "cats": ["y"]},
    }
    out = decide_arm_c(
        by_model,
        models=TRIO_B,
        judge_fn=judge_fn,
        expected_gene_id="b0090",
        expected_name="murG",
        excerpt="text",
        field_keys=["function", "cats"],
    )
    assert out == {"function": None, "cats": None}


def _arm_d_fixture():
    from experiments.paper.runners.consensus_arms_claims import build_claims_for_trio

    models = TRIO_B
    by_model = {
        "gemma4:12b": {
            "function": "Builds the cell wall. Totally invented sentence.",
            "functional_category": ["peptidoglycan biosynthesis", "made up pathway"],
            "drug_susc_impact": "Mutants resist drug X.",
            "infection_impact": "Unsupported infection claim.",
            "essential_in_vitro": True,
            "essential_in_vivo": False,
        },
        "phi4:14b": {
            "function": None,
            "functional_category": None,
            "essential_in_vitro": True,
        },
        "dolphin3:8b": {
            "function": None,
            "functional_category": None,
            "essential_in_vitro": False,
        },
    }
    claims = build_claims_for_trio(
        by_model, models, organism="Mtb", gene_id="Rv0001", gene_name="murA"
    )
    return models, by_model, claims


def _score_by_text(claims, passing):
    """Score 0.9 if any `passing` substring occurs in the claim text, else 0.1."""
    return {
        c["claim_index"]: 0.9 if any(p in c["text"] for p in passing) else 0.1
        for c in claims
    }


def test_decide_arm_d_keeps_passing_tags_only():
    from experiments.paper.runners.consensus_arms_decide import decide_arm_d

    models, by_model, claims = _arm_d_fixture()
    scores = _score_by_text(claims, ["peptidoglycan biosynthesis"])
    out = decide_arm_d(
        by_model, models=models, claims=claims,
        scores_by_claim_id=scores, threshold=0.5,
    )
    assert out["functional_category"] == ["peptidoglycan biosynthesis"]


def test_decide_arm_d_reassembles_strings_and_bools():
    from experiments.paper.runners.consensus_arms_decide import decide_arm_d

    models, by_model, claims = _arm_d_fixture()
    scores = _score_by_text(
        claims,
        ["Builds the cell wall.", "Mutants resist", "is essential in vitro",
         "is not essential in vitro"],
    )
    out = decide_arm_d(
        by_model, models=models, claims=claims,
        scores_by_claim_id=scores, threshold=0.5,
    )
    assert out["function"] == "Builds the cell wall."
    assert "invented" not in out["function"]
    assert out["drug_susc_impact"].endswith("Mutants resist drug X.")
    # infection claim failed -> null
    assert out["infection_impact"] is None
    # 2 passing True vs 1 passing False -> majority True
    assert out["essential_in_vitro"] is True
    # in vivo claim failed -> null
    assert out["essential_in_vivo"] is None


def test_decide_arm_d_joins_multiple_kept_sentences_and_nulls_empty_fields():
    from experiments.paper.runners.consensus_arms_decide import decide_arm_d

    models, by_model, claims = _arm_d_fixture()
    scores = _score_by_text(claims, ["Builds the cell wall.", "invented sentence"])
    out = decide_arm_d(
        by_model, models=models, claims=claims,
        scores_by_claim_id=scores, threshold=0.5,
    )
    assert out["function"] == "Builds the cell wall. Totally invented sentence."
    assert out["functional_category"] is None


def test_decide_arm_d_threshold_is_inclusive_and_bool_tie_is_null():
    from experiments.paper.runners.consensus_arms_decide import decide_arm_d

    models, by_model, claims = _arm_d_fixture()
    in_vitro = [c for c in claims if c["field"] == "essential_in_vitro"]
    scores = {c["claim_index"]: 0.0 for c in claims}
    # keep exactly one True and one False in-vitro claim, at the threshold
    keep_true = next(c for c in in_vitro if c["source_value"] is True)
    keep_false = next(c for c in in_vitro if c["source_value"] is False)
    scores[keep_true["claim_index"]] = 0.5
    scores[keep_false["claim_index"]] = 0.5
    out = decide_arm_d(
        by_model, models=models, claims=claims,
        scores_by_claim_id=scores, threshold=0.5,
    )
    assert out["essential_in_vitro"] is None
