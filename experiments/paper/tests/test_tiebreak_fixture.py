from pathlib import Path

from experiments.paper.runners.tiebreak_fixture import (
    filter_cases,
    load_tiebreak_fixture,
    validate_case,
)


FIXTURE = Path(
    "experiments/paper/fixtures/constructed/tiebreak_consensus_v1.json"
)


def test_suite_mix_and_size():
    items = load_tiebreak_fixture(FIXTURE)
    assert len(items) == 32
    assert sum(1 for item in items if not item["expect_llm"]) == 8


def test_apples_case_present():
    items = load_tiebreak_fixture(FIXTURE)
    apples = next(
        item
        for item in items
        if item["case_id"] == "general-apples-paraphrase-001"
    )
    assert apples["expected"] == "apples are red and delicious"
    assert len(apples["candidates"]) == 3


def test_validate_exact_majority_has_two_identical():
    case = {
        "case_id": "x",
        "domain": "general",
        "case_family": "exact_majority",
        "experiment_tags": ["tiebreak-non-nonsense"],
        "field_key": "answer",
        "expect_llm": False,
        "expected": "the sky is blue",
        "candidates": [
            {"answer": "the sky is blue"},
            {"answer": "nope"},
            {"answer": "the sky is blue"},
        ],
    }
    assert validate_case(case) == []


def test_filter_by_experiment_tag():
    items = load_tiebreak_fixture(FIXTURE)
    nonsense = filter_cases(items, ["tiebreak-nonsense"])
    assert nonsense
    assert all(
        "tiebreak-nonsense" in item["experiment_tags"] for item in nonsense
    )


def test_validate_rejects_wrong_candidate_shape():
    case = {
        "case_id": "bad-shape",
        "case_family": "exact_majority",
        "field_key": "answer",
        "expect_llm": False,
        "expected": "yes",
        "candidates": [{"answer": "yes"}, {}],
    }
    errors = validate_case(case)
    assert any("exactly 3 candidates" in error for error in errors)
    assert any("missing field_key" in error for error in errors)


def test_validate_paraphrase_requires_semantic_pair_without_exact_majority():
    valid = {
        "case_id": "paraphrase",
        "case_family": "paraphrase_majority",
        "field_key": "answer",
        "expect_llm": True,
        "expected": "apples are red and delicious",
        "candidates": [
            {"answer": "bananas are yellow"},
            {"answer": "red apples are delicious fruit"},
            {"answer": "delicious apples have red skin"},
        ],
    }
    assert validate_case(valid) == []

    exact_majority = {
        **valid,
        "candidates": [
            {"answer": "bananas are yellow"},
            {"answer": "apples are red and delicious"},
            {"answer": "Apples are red and delicious"},
        ],
    }
    assert any(
        "deterministic exact majority" in error
        for error in validate_case(exact_majority)
    )


def test_validate_null_expected_requires_mutually_distinct_candidates():
    case = {
        "case_id": "split",
        "case_family": "hard_split_null",
        "field_key": "answer",
        "expect_llm": True,
        "expected": None,
        "candidates": [
            {"answer": "red"},
            {"answer": "blue"},
            {"answer": " Red "},
        ],
    }
    assert any("mutually non-matching" in error for error in validate_case(case))


def test_validate_extractor_zero_minority_is_not_soft_match():
    case = {
        "case_id": "minority",
        "case_family": "paraphrase_majority",
        "field_key": "answer",
        "expect_llm": True,
        "expected": "apples are red and delicious",
        "agreement": {"extractor_0_is_minority": True},
        "candidates": [
            {"answer": "red delicious apples"},
            {"answer": "red apples are delicious fruit"},
            {"answer": "delicious apples have red skin"},
        ],
    }
    assert any("extractor_0 minority" in error for error in validate_case(case))
