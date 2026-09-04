from autoannotation.consensus import FieldSpec
from experiments.paper.runners import general_consensus
from experiments.paper.runners.general_consensus import (
    GENERAL_BATCH_CONSENSUS_PROMPT,
    GENERAL_FIELD_SPECS,
    make_biology_batch_merger,
    make_general_batch_merger,
)


def test_general_prompt_is_candidate_only():
    prompt = GENERAL_BATCH_CONSENSUS_PROMPT.lower()
    assert (
        "do not have access to the source text" in prompt
        or "candidates only" in prompt
        or "only from the candidate" in prompt
    )
    assert "majority" in prompt


def test_general_field_specs_define_answer_string():
    assert GENERAL_FIELD_SPECS == (FieldSpec("answer", "string"),)


def test_general_merger_calls_ollama_with_requested_field_schema(monkeypatch):
    captured = {}

    def fake_chat(**kwargs):
        captured.update(kwargs)
        return {"message": {"content": '{"answer": "red apples are delicious"}'}}

    monkeypatch.setattr(general_consensus, "ollama_chat", fake_chat)

    merger = make_general_batch_merger("test-model")
    result = merger(
        [{"answer": "red apples"}, {"answer": "delicious red apples"}],
        ["answer"],
    )

    assert result == {"answer": "red apples are delicious"}
    assert captured["model"] == "test-model"
    assert captured["json_schema"]["required"] == ["answer"]
    assert captured["json_schema"]["additionalProperties"] is False


def test_biology_merger_wraps_handler_batch_merge():
    class FakeHandler:
        def _ollama_batch_consensus_merge(
            self, candidates, unresolved_fields, *, model
        ):
            assert candidates == [{"function": "replication"}]
            assert unresolved_fields == ["function"]
            assert model == "qwen3:8b"
            return {"function": "replication"}, 0.25

    merger = make_biology_batch_merger(FakeHandler())

    assert merger([{"function": "replication"}], ["function"]) == {
        "function": "replication"
    }
