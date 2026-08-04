import json

import run_pipeline


def test_record_result_appends_jsonl(tmp_path, monkeypatch):
    scores = tmp_path / "pipeline_scores.jsonl"
    monkeypatch.setattr(run_pipeline, "SCORES_LOG", str(scores))

    run_pipeline.record_result(
        "Rv0001",
        {"score": 0.9},
        12.5,
        3,
        10,
        1.25,
    )
    run_pipeline.record_result("Rv0002", "N/A", "N/A", 0, "N/A")

    lines = scores.read_text().strip().splitlines()
    assert len(lines) == 2

    first = json.loads(lines[0])
    assert first["gene"] == "Rv0001"
    assert first["comparison_result"] == {"score": 0.9}
    assert first["duration"] == 12.5
    assert first["num_papers_used"] == 3
    assert first["num_total_papers"] == 10
    assert first["cumulative_relevance"] == 1.25
    assert "timestamp" in first

    second = json.loads(lines[1])
    assert second["gene"] == "Rv0002"
    assert second["comparison_result"] == "N/A"
    assert second["cumulative_relevance"] == 0.0
