from experiments.paper.runners.consensus_arms_decide import (
    JUDGE_MODEL,
    TRIO_B,
    TRIO_BREF,
    decide_arm_a,
    decide_arm_b,
    decide_arm_c,
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
