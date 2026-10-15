from experiments.paper.runners.consensus_arms_judge_c import (
    ARM_C_JUDGE_PROMPT,
    build_arm_c_prompt,
    make_ollama_judge_fn,
    select_supported_verbatim,
)


def test_prompt_includes_excerpt_and_gene():
    prompt = build_arm_c_prompt(
        gene_id="b0090",
        gene_name="murG",
        excerpt="murG (b0090) is in the peptidoglycan trail.",
        candidates=[{"function": "MurG participates in peptidoglycan biosynthesis."}],
        field_keys=["function"],
    )
    assert "murG" in prompt and "b0090" in prompt
    assert "peptidoglycan trail" in prompt
    assert "VERBATIM" in prompt.upper() or "verbatim" in prompt


def test_prompt_template_has_required_rules_and_placeholders():
    for token in ("{gene_name}", "{gene_id}", "{excerpt}", "{candidates_json}", "{field_list}"):
        assert token in ARM_C_JUDGE_PROMPT
    assert "VERBATIM" in ARM_C_JUDGE_PROMPT
    assert "prefer the shorter value" in ARM_C_JUDGE_PROMPT
    assert "another gene" in ARM_C_JUDGE_PROMPT


def test_prompt_only_lists_requested_fields_and_keeps_null_candidates():
    prompt = build_arm_c_prompt(
        gene_id="b0090",
        gene_name="murG",
        excerpt="x",
        candidates=[{"function": None, "other": "zzz-hidden"}, {"function": "f"}],
        field_keys=["function"],
    )
    assert "zzz-hidden" not in prompt
    assert "null" in prompt


def test_select_rejects_invention():
    cands = [{"function": "MurG participates in peptidoglycan biosynthesis."}]
    payload = {"function": "MurG is a transcription factor."}
    out = select_supported_verbatim(payload, cands, ["function"])
    assert out["function"] is None


def test_select_keeps_candidate_string():
    cands = [{"function": "MurG participates in peptidoglycan biosynthesis."}]
    payload = {"function": "MurG participates in peptidoglycan biosynthesis."}
    out = select_supported_verbatim(payload, cands, ["function"])
    assert out["function"] == cands[0]["function"]


def test_select_returns_candidate_wording_for_soft_match():
    cand = "MurG participates in peptidoglycan biosynthesis in the cell wall."
    cands = [{"function": cand}]
    payload = {"function": "MurG participates in peptidoglycan biosynthesis in the cell wall"}
    out = select_supported_verbatim(payload, cands, ["function"])
    assert out["function"] == cand


def test_select_only_returns_requested_keys_and_nulls_missing():
    cands = [{"function": "f", "other": "o"}]
    out = select_supported_verbatim({"other": "o"}, cands, ["function"])
    assert out == {"function": None}


def test_select_null_and_empty_stay_null():
    cands = [{"function": "alpha beta"}]
    assert select_supported_verbatim({"function": None}, cands, ["function"]) == {
        "function": None
    }
    assert select_supported_verbatim({"function": ""}, cands, ["function"]) == {
        "function": None
    }


def test_select_arrays_set_equal_order_insensitive():
    cands = [{"cats": ["a", "b"]}, {"cats": ["c"]}]
    assert select_supported_verbatim({"cats": ["b", "a"]}, cands, ["cats"])["cats"] == [
        "a",
        "b",
    ]


def test_select_arrays_reject_subset_superset_and_union():
    cands = [{"cats": ["a", "b"]}, {"cats": ["c"]}]
    assert select_supported_verbatim({"cats": ["a"]}, cands, ["cats"])["cats"] is None
    assert select_supported_verbatim({"cats": ["a", "b", "c"]}, cands, ["cats"])["cats"] is None


def test_select_booleans_exact():
    cands = [{"flag": True}, {"flag": None}]
    assert select_supported_verbatim({"flag": True}, cands, ["flag"])["flag"] is True
    assert select_supported_verbatim({"flag": False}, cands, ["flag"])["flag"] is None


def test_select_bool_not_confused_with_string_or_int():
    cands = [{"flag": True}]
    assert select_supported_verbatim({"flag": "true"}, cands, ["flag"])["flag"] is None
    assert select_supported_verbatim({"flag": 1}, cands, ["flag"])["flag"] is None


def test_select_type_mismatch_string_vs_array_rejected():
    cands = [{"f": ["a"]}]
    assert select_supported_verbatim({"f": "a"}, cands, ["f"])["f"] is None


def test_make_ollama_judge_fn_wires_judge_model(monkeypatch):
    seen = {}

    def fake_chat(**kwargs):
        seen.update(kwargs)
        return {"message": {"content": '{"function": "f"}'}}

    monkeypatch.setattr(
        "experiments.paper.runners.consensus_arms_judge_c.ollama_chat", fake_chat
    )
    judge_fn = make_ollama_judge_fn()
    out = judge_fn(
        candidates=[{"function": "f"}],
        field_keys=["function"],
        excerpt="ex",
        gene_id="b0090",
        gene_name="murG",
    )
    assert out == {"function": "f"}
    assert seen["model"] == "gemma4:26b"
    assert seen["json_schema"]["required"] == ["function"]
    assert "ex" in seen["messages"][0]["content"]
