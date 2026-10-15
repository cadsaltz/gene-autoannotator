from pathlib import Path
import json
from experiments.paper.runners.consensus_arms_io import (
    packet_stem,
    load_biology_trials,
    extractor_outputs_by_model,
    load_labels,
)

def test_packet_stem_replaces_hash():
    assert packet_stem("t010_b0090_PMC6327494_results#2") == "t010_b0090_PMC6327494_results_2"

def test_load_biology_skips_general(tmp_path: Path):
    rows = [
        {"record_type": "trial_observable", "trial_pool": "general", "trial_id": "g1",
         "outputs": {}, "condition_metrics": {}},
        {"record_type": "trial_observable", "trial_pool": "biology", "trial_id": "b1",
         "outputs": {"extractor_A": {"function": None}},
         "condition_metrics": {"extractor_A": {"model": "gemma4:12b"}}},
        {"record_type": "manifest", "trial_pool": "biology"},
    ]
    p = tmp_path / "records.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    trials = load_biology_trials(p)
    assert len(trials) == 1 and trials[0]["trial_id"] == "b1"

def test_extractor_outputs_by_model_maps_letters():
    trial = {
        "outputs": {"extractor_A": {"function": "x"}, "extractor_D": {"function": "y"},
                    "consensus_D": {"function": None}},
        "condition_metrics": {
            "extractor_A": {"model": "gemma4:12b"},
            "extractor_D": {"model": "dolphin3:8b"},
            "consensus_D": {"model": "qwen3.5:9b"},
        },
    }
    by_m = extractor_outputs_by_model(trial)
    assert by_m["gemma4:12b"]["function"] == "x"
    assert by_m["dolphin3:8b"]["function"] == "y"
    assert "qwen3.5:9b" not in by_m
