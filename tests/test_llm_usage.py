import json
from pathlib import Path

from autoannotation import llms
from autoannotation import organisms


def _ollama_response(content, **metrics):
    return {
        "message": {"content": json.dumps(content)},
        "total_duration": 2_000_000_000,
        **metrics,
    }


def test_llm_handler_summarizes_live_ollama_token_usage(monkeypatch, tmp_path):
    handler = llms.LlmHandler(cache_dir=tmp_path)
    profile = organisms.resolve_profile("mtb-h37rv")

    def fake_chat(**kwargs):
        return _ollama_response(
            {
                "gene_id": "Rv0001",
                "name": "dnaA",
                "function": "Initiates chromosomal replication.",
            },
            prompt_eval_count=42,
            eval_count=7,
            load_duration=100_000_000,
            prompt_eval_duration=300_000_000,
            eval_duration=600_000_000,
        )

    monkeypatch.setattr(llms.ollama, "chat", fake_chat)

    handler.get_llm_gene_info_json(
        "Rv0001",
        "dnaA",
        "Rv0001 dnaA initiates replication.",
        "fake-model",
        section_type="abstract",
        organism_profile=profile,
    )

    usage = handler.summarize_usage()

    assert usage["calls"] == 1
    assert usage["known_input_tokens"] == 42
    assert usage["known_output_tokens"] == 7
    assert usage["known_total_tokens"] == 49
    assert usage["usage_records_with_missing_tokens"] == 0
    assert usage["by_role"]["section_summary"]["known_input_tokens"] == 42
    assert usage["by_model"]["fake-model"]["known_output_tokens"] == 7


def test_llm_handler_keeps_legacy_cached_responses_compatible(tmp_path):
    handler = llms.LlmHandler(cache_dir=tmp_path)
    profile = organisms.resolve_profile("mtb-h37rv")
    schema = llms.build_json_schema(profile)
    prompt = llms.build_section_prompt(
        "Rv0001",
        "dnaA",
        "Cached text.",
        section_type="abstract",
        organism_profile=profile,
    )
    cache_path = Path(handler._get_file("fake-model", prompt, schema))
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps({
            "duration_sec": 0.1,
            "response_text": json.dumps({
                "gene_id": "Rv0001",
                "name": "dnaA",
            }),
        }),
        encoding="utf8",
    )

    handler.get_llm_gene_info_json(
        "Rv0001",
        "dnaA",
        "Cached text.",
        "fake-model",
        section_type="abstract",
        organism_profile=profile,
    )

    usage = handler.summarize_usage()

    assert usage["calls"] == 1
    assert usage["known_input_tokens"] == 0
    assert usage["known_output_tokens"] == 0
    assert usage["known_total_tokens"] == 0
    assert usage["usage_records_with_missing_tokens"] == 1
