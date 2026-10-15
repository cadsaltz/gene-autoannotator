import json
from pathlib import Path

import pytest
import yaml

from experiments.paper.runners import run_consensus_arms as runner


def _trial(idx: int) -> dict:
    return {
        "record_type": "trial_observable",
        "trial_pool": "biology",
        "trial_id": f"t{idx:03d}_b000{idx}_PMC1_results#1",
        "profile_id": "ecoli-k12-mg1655",
        "section": "results#1",
        "gene_id": f"b000{idx}",
        "gene_name": f"gene{idx}",
        "excerpt_text": f"Excerpt about gene{idx}. It does a thing.",
        "outputs": {
            "extractor_A": {"function": f"gemma function {idx}", "essential_in_vitro": True},
            "extractor_F": {"function": f"phi function {idx}"},
            "extractor_D": {"function": f"dolphin function {idx}"},
            "extractor_G": {"function": f"granite function {idx}"},
        },
        "condition_metrics": {
            "extractor_A": {"model": "gemma4:12b"},
            "extractor_F": {"model": "phi4:14b"},
            "extractor_D": {"model": "dolphin3:8b"},
            "extractor_G": {"model": "granite4.2:8b"},
        },
    }


@pytest.fixture
def setup(tmp_path: Path):
    records = tmp_path / "records.jsonl"
    rows = [
        {"record_type": "manifest", "trial_pool": "biology"},
        {"record_type": "trial_observable", "trial_pool": "general", "trial_id": "g1"},
        _trial(1),
        _trial(2),
    ]
    records.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    config = tmp_path / "config.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "experiment_id": "consensus-arms-test",
                "source_records": str(records),
                "labels_dir": str(tmp_path / "labels"),
                "judge_model": "gemma4:26b",
                "trio_b": ["gemma4:12b", "phi4:14b", "dolphin3:8b"],
                "trio_bref": ["gemma4:12b", "phi4:14b", "granite4.2:8b"],
                "classifiers": ["minicheck_ft5", "hhem", "bespoke_minicheck_7b"],
                "d_threshold": 0.5,
            }
        )
    )
    return tmp_path, config


def _run(tmp_path: Path, config: Path, *extra: str) -> Path:
    out_root = tmp_path / "out"
    rc = runner.main(
        ["--config", str(config), "--run-id", "r1", "--dry-run", "--out-root", str(out_root), *extra]
    )
    assert rc == 0
    return out_root


def _read_records(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def test_dry_run_arm_a_writes_records(setup):
    tmp_path, config = setup
    out_root = _run(tmp_path, config, "--arm", "A")
    arm_dir = out_root / "r1" / "arm_A"

    manifest = json.loads((arm_dir / "manifest.json").read_text())
    assert manifest["arm"] == "A"
    assert manifest["dry_run"] is True
    assert manifest["models"] == ["gemma4:12b"]
    assert manifest["n_trials"] == 2
    assert "git_sha" in manifest and "source_records" in manifest

    recs = _read_records(arm_dir / "records.jsonl")
    assert [r["trial_id"] for r in recs] == [
        "t001_b0001_PMC1_results#1",
        "t002_b0002_PMC1_results#1",
    ]
    for r in recs:
        assert {"trial_id", "excerpt_text", "candidates", "arm_output", "decision_metrics"} <= set(r)
        assert r["arm_output"]["function"].startswith("gemma function")
        assert set(r["candidates"]) == {"gemma4:12b"}


def test_resume_skips_existing_trials(setup):
    tmp_path, config = setup
    out_root = _run(tmp_path, config, "--arm", "A", "--max-trials", "1")
    recs_path = out_root / "r1" / "arm_A" / "records.jsonl"
    assert len(_read_records(recs_path)) == 1

    _run(tmp_path, config, "--arm", "A")
    recs = _read_records(recs_path)
    assert len(recs) == 2
    assert len({r["trial_id"] for r in recs}) == 2


def test_dry_run_other_arms_use_stubs_and_safe_dir_name(setup):
    tmp_path, config = setup
    for arm, dirname in [
        ("B", "arm_B"),
        ("B-ref", "arm_B-ref"),
        ("C", "arm_C"),
        ("D:hhem", "arm_D_hhem"),
    ]:
        out_root = _run(tmp_path, config, "--arm", arm)
        arm_dir = out_root / "r1" / dirname
        recs = _read_records(arm_dir / "records.jsonl")
        assert len(recs) == 2, arm
        assert recs[0]["arm_output"] is not None
        assert (arm_dir / "manifest.json").exists()
    assert set(_read_records(out_root / "r1" / "arm_B" / "records.jsonl")[0]["candidates"]) == {
        "gemma4:12b",
        "phi4:14b",
        "dolphin3:8b",
    }


def test_rejects_unknown_arm(setup):
    tmp_path, config = setup
    with pytest.raises(SystemExit):
        runner.main(["--config", str(config), "--run-id", "r1", "--arm", "Z", "--dry-run"])


def test_rejects_dry_run_flag_mismatch_on_resume(setup):
    tmp_path, config = setup
    out_root = tmp_path / "out"
    base = [
        "--config",
        str(config),
        "--run-id",
        "r1",
        "--arm",
        "A",
        "--out-root",
        str(out_root),
    ]
    assert runner.main([*base, "--dry-run"]) == 0
    rc = runner.main(base)
    assert rc == 1
