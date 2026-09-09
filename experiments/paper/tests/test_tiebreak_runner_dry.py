import csv
import json
from pathlib import Path

from experiments.paper.runners.run_tiebreak_consensus import (
    NONSENSE_EXPERIMENT_TAG,
    _aggregate_row,
    _aggregate_rows,
    run_experiment,
)


CONFIG = Path("experiments/paper/configs/tiebreak-non-nonsense.yaml")
COMBINED_CONFIG = Path("experiments/paper/configs/tiebreak-consensus.yaml")


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
    assert manifest["model_tags"]["consensus"] == "qwen3.5:27b"
    assert manifest["dry_run"] is True
    assert manifest["case_selection"] == {
        "include_tags": ["tiebreak-non-nonsense"],
        "match_any": True,
    }
    assert manifest["case_counts_by_tag"] == {"tiebreak-non-nonsense": 5}

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


def _make_record(
    *,
    case_id: str,
    condition: str,
    experiment_tags: list[str],
    case_family: str = "exact_majority",
    match_soft: bool = True,
) -> dict:
    return {
        "case_id": case_id,
        "condition": condition,
        "experiment_tags": experiment_tags,
        "case_family": case_family,
        "domain": "general",
        "expect_llm": False,
        "match_exact": match_soft,
        "match_soft": match_soft,
        "llm_invoked": False,
        "expect_llm_matched": True,
        "invention": False,
    }


def test_aggregate_row_nonsense_metric_uses_tag_not_family():
    """Nonsense adoption rate must not be diluted by non-nonsense tag rows."""
    records = [
        _make_record(
            case_id="nn-1",
            condition="no_consensus_pick_extractor_0",
            experiment_tags=["tiebreak-non-nonsense"],
            match_soft=False,
        ),
        _make_record(
            case_id="nn-1",
            condition="hybrid_consensus",
            experiment_tags=["tiebreak-non-nonsense"],
            match_soft=True,
        ),
        _make_record(
            case_id="ns-1",
            condition="no_consensus_pick_extractor_0",
            experiment_tags=[NONSENSE_EXPERIMENT_TAG],
            case_family="exact_majority_nonsense",
            match_soft=False,
        ),
        _make_record(
            case_id="ns-1",
            condition="hybrid_consensus",
            experiment_tags=[NONSENSE_EXPERIMENT_TAG],
            case_family="exact_majority_nonsense",
            match_soft=True,
        ),
    ]
    overall = _aggregate_row(records, scope="overall", value="all")
    assert overall["case_count"] == 2
    assert overall["nonsense_majority_adoption_rate"] == 1.0

    non_nonsense = _aggregate_row(
        [record for record in records if "tiebreak-non-nonsense" in record["experiment_tags"]],
        scope="experiment_tag",
        value="tiebreak-non-nonsense",
    )
    assert non_nonsense["nonsense_majority_adoption_rate"] == 0.0

    nonsense = _aggregate_row(
        [record for record in records if NONSENSE_EXPERIMENT_TAG in record["experiment_tags"]],
        scope="experiment_tag",
        value=NONSENSE_EXPERIMENT_TAG,
    )
    assert nonsense["nonsense_majority_adoption_rate"] == 1.0


def test_aggregate_rows_emits_experiment_tag_scope():
    records = [
        _make_record(
            case_id="a",
            condition="hybrid_consensus",
            experiment_tags=["tiebreak-non-nonsense"],
        ),
        _make_record(
            case_id="b",
            condition="hybrid_consensus",
            experiment_tags=[NONSENSE_EXPERIMENT_TAG],
            case_family="exact_majority_nonsense",
        ),
    ]
    rows = _aggregate_rows(records)
    tag_rows = [row for row in rows if row["scope"] == "experiment_tag"]
    assert {row["value"] for row in tag_rows} == {
        "tiebreak-non-nonsense",
        NONSENSE_EXPERIMENT_TAG,
    }


def test_dry_run_combined_config_emits_tag_scoped_aggregates(tmp_path, monkeypatch):
    def fail_if_called(*args, **kwargs):
        raise AssertionError("dry-run must not call Ollama")

    monkeypatch.setattr(
        "experiments.paper.runners.general_consensus.ollama_chat",
        fail_if_called,
    )

    run_dir = run_experiment(
        config_path=COMBINED_CONFIG,
        run_id="combined-drytest",
        dry_run=True,
        limit=10,
        results_root=tmp_path,
    )

    manifest = json.loads((run_dir / "manifest.json").read_text())
    assert manifest["case_selection"] == {
        "include_tags": ["tiebreak-non-nonsense", "tiebreak-nonsense"],
        "match_any": True,
    }
    assert set(manifest["case_counts_by_tag"]) == {
        "tiebreak-non-nonsense",
        "tiebreak-nonsense",
    }

    records = [
        json.loads(line)
        for line in (run_dir / "records.jsonl").read_text().splitlines()
    ]
    record_tags = {
        tag
        for record in records
        for tag in record.get("experiment_tags", [])
    }
    assert "tiebreak-non-nonsense" in record_tags
    assert "tiebreak-nonsense" in record_tags

    aggregates = list(csv.DictReader((run_dir / "aggregate.csv").open()))
    tag_rows = [row for row in aggregates if row["scope"] == "experiment_tag"]
    assert {row["value"] for row in tag_rows} == {
        "tiebreak-non-nonsense",
        "tiebreak-nonsense",
    }
    nonsense_row = next(
        row for row in tag_rows if row["value"] == NONSENSE_EXPERIMENT_TAG
    )
    non_nonsense_row = next(
        row for row in tag_rows if row["value"] == "tiebreak-non-nonsense"
    )
    assert float(nonsense_row["nonsense_majority_adoption_rate"]) > 0.0
    assert float(non_nonsense_row["nonsense_majority_adoption_rate"]) == 0.0
