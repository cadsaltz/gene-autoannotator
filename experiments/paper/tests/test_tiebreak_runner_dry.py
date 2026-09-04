import csv
import json
from pathlib import Path

from experiments.paper.runners.run_tiebreak_consensus import run_experiment


CONFIG = Path("experiments/paper/configs/tiebreak-non-nonsense.yaml")


def test_dry_run_writes_scored_artifacts_without_ollama(tmp_path, monkeypatch):
    def fail_if_called(*args, **kwargs):
        raise AssertionError("dry-run must not call Ollama")

    monkeypatch.setattr(
        "experiments.paper.runners.general_consensus.ollama_chat",
        fail_if_called,
    )

    run_dir = run_experiment(
        config_path=CONFIG,
        run_id="drytest",
        dry_run=True,
        limit=5,
        results_root=tmp_path,
    )

    assert (run_dir / "manifest.json").is_file()
    assert (run_dir / "records.jsonl").is_file()
    assert (run_dir / "aggregate.csv").is_file()

    manifest = json.loads((run_dir / "manifest.json").read_text())
    assert manifest["model_tags"]["consensus"] == "qwen3:0.6b"
    assert manifest["dry_run"] is True

    records = [
        json.loads(line)
        for line in (run_dir / "records.jsonl").read_text().splitlines()
    ]
    assert len(records) == 10
    assert {record["condition"] for record in records} == {
        "no_consensus_pick_extractor_0",
        "hybrid_consensus",
    }
    assert all(
        {"expected", "observed", "llm_invoked", "provenance"} <= record.keys()
        for record in records
    )
    assert any(
        record["condition"] == "hybrid_consensus" and record["llm_invoked"]
        for record in records
    )

    aggregates = list(csv.DictReader((run_dir / "aggregate.csv").open()))
    assert aggregates
    assert {
        "consensus_match_soft_rate",
        "baseline_match_soft_rate",
        "necessity_delta",
        "llm_invoked_rate",
        "expect_llm_calibration_rate",
        "invention_rate",
    } <= aggregates[0].keys()
