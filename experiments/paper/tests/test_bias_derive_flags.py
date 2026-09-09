import json
import logging
from pathlib import Path

import pytest

from experiments.paper.runners import run_bias_1_vs_3


def _minimal_bias_config(tmp_path: Path) -> Path:
    fixture_path = tmp_path / "fixture.json"
    fixture_path.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "trial_id": "trial-1",
                        "trial_pool": "biology",
                        "profile_id": "mtb-h37rv",
                        "gene_id": "Rv0001",
                        "gene_name": "dnaA",
                        "pmc_id": "PMC1",
                        "section": "results",
                        "excerpt_text": "short excerpt",
                    }
                ],
            }
        )
    )
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "experiment_id: bias-1-vs-3-small\n"
        "n_trials: 1\n"
        "fixtures:\n"
        f"  papers: {fixture_path}\n"
        "models:\n"
        "  extractors: [model-a, model-b, model-c]\n"
        "  consensus: model-d\n"
    )
    return config_path


def test_dry_run_derive_flags_invoke_derives_and_write_manifest(
    tmp_path,
    monkeypatch,
):
    paper_dir = tmp_path / "paper"
    monkeypatch.setattr(run_bias_1_vs_3, "PAPER_DIR", paper_dir)
    config_path = _minimal_bias_config(tmp_path)

    split_out = paper_dir / "results" / "split-vs-not" / "split_from_dry-derive"
    cost_out = paper_dir / "results" / "cost-benefit-1-vs-3" / "cost_from_dry-derive"
    calls: list[tuple[str, dict]] = []

    def fake_split(*, bias_run_dir, run_id=None, config_path=None):
        calls.append(
            (
                "split",
                {
                    "bias_run_dir": Path(bias_run_dir),
                    "run_id": run_id,
                },
            )
        )
        split_out.mkdir(parents=True, exist_ok=True)
        return split_out

    def fake_cost(
        *,
        bias_run_dir,
        run_id=None,
        config_path=None,
        include_extractors=True,
    ):
        calls.append(
            (
                "cost",
                {
                    "bias_run_dir": Path(bias_run_dir),
                    "run_id": run_id,
                },
            )
        )
        cost_out.mkdir(parents=True, exist_ok=True)
        return cost_out

    monkeypatch.setattr(
        "experiments.paper.runners.derive_split_vs_not.derive_split_vs_not",
        fake_split,
    )
    monkeypatch.setattr(
        "experiments.paper.runners.derive_cost_benefit_1_vs_3.derive_cost_benefit_1_vs_3",
        fake_cost,
    )

    output_dir = run_bias_1_vs_3.run_bias_experiment(
        config_path=config_path,
        run_id="dry-derive",
        dry_run=True,
        derive_split=True,
        derive_cost=True,
    )

    assert output_dir.is_dir()
    assert (output_dir / "records.jsonl").is_file()
    assert (output_dir / "aggregate.csv").is_file()

    assert len(calls) == 2
    assert calls[0][0] == "split"
    assert calls[0][1]["bias_run_dir"] == output_dir
    assert calls[0][1]["run_id"] == "split_from_dry-derive"
    assert calls[1][0] == "cost"
    assert calls[1][1]["bias_run_dir"] == output_dir
    assert calls[1][1]["run_id"] == "cost_from_dry-derive"

    manifest = json.loads((output_dir / "manifest.json").read_text())
    assert manifest["derived"] == {
        "split": str(split_out),
        "cost": str(cost_out),
    }


def test_derive_failure_warns_and_continues(tmp_path, monkeypatch, caplog):
    paper_dir = tmp_path / "paper"
    monkeypatch.setattr(run_bias_1_vs_3, "PAPER_DIR", paper_dir)
    config_path = _minimal_bias_config(tmp_path)

    def boom(*, bias_run_dir, run_id=None, config_path=None):
        raise RuntimeError("derive boom")

    monkeypatch.setattr(
        "experiments.paper.runners.derive_split_vs_not.derive_split_vs_not",
        boom,
    )

    with caplog.at_level(logging.WARNING):
        output_dir = run_bias_1_vs_3.run_bias_experiment(
            config_path=config_path,
            run_id="dry-derive-warn",
            dry_run=True,
            derive_split=True,
            derive_cost=False,
        )

    assert (output_dir / "aggregate.csv").is_file()
    manifest = json.loads((output_dir / "manifest.json").read_text())
    assert manifest["derived"] == {"split": None}
    assert any(
        record.levelno == logging.WARNING and "derive" in record.message.lower()
        for record in caplog.records
    )


def test_spreadsheet_strict_reraises_derive_failure(tmp_path, monkeypatch):
    paper_dir = tmp_path / "paper"
    monkeypatch.setattr(run_bias_1_vs_3, "PAPER_DIR", paper_dir)
    config_path = _minimal_bias_config(tmp_path)

    def boom(*, bias_run_dir, run_id=None, config_path=None):
        raise RuntimeError("derive boom")

    monkeypatch.setattr(
        "experiments.paper.runners.derive_split_vs_not.derive_split_vs_not",
        boom,
    )

    with pytest.raises(RuntimeError, match="derive boom"):
        run_bias_1_vs_3.run_bias_experiment(
            config_path=config_path,
            run_id="dry-derive-strict",
            dry_run=True,
            derive_split=True,
            spreadsheet_strict=True,
        )


def test_parse_args_accepts_derive_flags(monkeypatch):
    import sys

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "prog",
            "--config",
            "x.yaml",
            "--derive-split",
            "--derive-cost",
            "--dry-run",
        ],
    )
    args = run_bias_1_vs_3._parse_args()
    assert args.derive_split is True
    assert args.derive_cost is True
    assert args.dry_run is True
