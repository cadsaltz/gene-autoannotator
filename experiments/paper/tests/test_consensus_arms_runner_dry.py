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


def _live_args(tmp_path: Path, config: Path, arm: str) -> list[str]:
    return [
        "--config",
        str(config),
        "--run-id",
        "live1",
        "--arm",
        arm,
        "--out-root",
        str(tmp_path / "out"),
        "--max-trials",
        "1",
    ]


def test_live_b_uses_production_batch_merger_with_judge_model(setup, monkeypatch):
    """Non-dry-run B wires make_production_batch_merger(model=JUDGE_MODEL); no network."""
    from unittest.mock import MagicMock

    from autoannotation import llms, organisms
    from experiments.paper.runners import consensus_arms_decide as decide

    tmp_path, config = setup
    handler = MagicMock(name="LlmHandler-instance")
    handler._ollama_batch_consensus_merge.return_value = ({"function": "merged"}, 0.1)
    handler_cls = MagicMock(name="LlmHandler", return_value=handler)
    profile = MagicMock(name="profile", canonical_name="Escherichia coli")
    monkeypatch.setattr(llms, "LlmHandler", handler_cls)
    monkeypatch.setattr(organisms, "resolve_profile", lambda _pid: profile)
    monkeypatch.setattr("autoannotation.worker_env.load_worker_env_into_process", lambda **kw: None)

    seen: dict = {}
    real_factory = decide.make_production_batch_merger

    def spy_factory(llm_handler, **kwargs):
        seen["handler"] = llm_handler
        seen["kwargs"] = kwargs
        return real_factory(llm_handler, **kwargs)

    def fake_hybrid(candidates, **kwargs):
        seen["n_candidates"] = len(candidates)
        merged = kwargs["batch_merger"](candidates, ["function"])
        return merged, {"function": "judge"}, 1

    monkeypatch.setattr(runner, "make_production_batch_merger", spy_factory)
    monkeypatch.setattr(decide, "hybrid_section_consensus", fake_hybrid)

    assert runner.main(_live_args(tmp_path, config, "B")) == 0

    assert seen["handler"] is handler
    assert seen["kwargs"]["model"] == decide.JUDGE_MODEL == "gemma4:26b"
    assert seen["kwargs"]["organism_profile"] is profile
    assert seen["n_candidates"] == 3
    handler._ollama_batch_consensus_merge.assert_called_once()
    assert handler._ollama_batch_consensus_merge.call_args.kwargs["model"] == decide.JUDGE_MODEL

    recs = _read_records(tmp_path / "out" / "live1" / "arm_B" / "records.jsonl")
    assert len(recs) == 1 and recs[0]["arm_output"] == {"function": "merged"}
    manifest = json.loads((tmp_path / "out" / "live1" / "arm_B" / "manifest.json").read_text())
    assert manifest["dry_run"] is False and manifest["judge_model"] == "gemma4:26b"


def test_live_b_soft_fails_trial_without_crashing_arm(setup, monkeypatch):
    from unittest.mock import MagicMock

    from autoannotation import llms, organisms

    tmp_path, config = setup
    handler = MagicMock()
    handler._ollama_batch_consensus_merge.side_effect = RuntimeError("ollama down")
    monkeypatch.setattr(llms, "LlmHandler", MagicMock(return_value=handler))
    monkeypatch.setattr(organisms, "resolve_profile", lambda _pid: None)
    monkeypatch.setattr("autoannotation.worker_env.load_worker_env_into_process", lambda **kw: None)
    # candidates disagree on "function" so the merger is genuinely needed
    rc = runner.main(_live_args(tmp_path, config, "B"))
    arm_dir = tmp_path / "out" / "live1" / "arm_B"
    manifest = json.loads((arm_dir / "manifest.json").read_text())
    assert rc == 1
    assert manifest["status"] == "complete_with_errors"
    assert manifest["n_errors"] == 1
    errors = _read_records(arm_dir / "errors.jsonl")
    assert "ollama down" in errors[0]["error"]
    assert not (arm_dir / "records.jsonl").exists()


def test_main_loads_worker_env_only_when_live(setup, monkeypatch):
    tmp_path, config = setup
    calls: list[int] = []
    monkeypatch.setattr(
        "autoannotation.worker_env.load_worker_env_into_process",
        lambda **kw: calls.append(1),
    )
    assert runner.main(["--config", str(config), "--run-id", "d", "--arm", "A", "--dry-run",
                        "--out-root", str(tmp_path / "out")]) == 0
    assert calls == []
    assert runner.main(["--config", str(config), "--run-id", "l", "--arm", "A",
                        "--out-root", str(tmp_path / "out")]) == 0
    assert calls == [1]
