"""Sequential consensus-arms pilot runner (Phase 1).

One process runs exactly one arm over every biology trial in the source
records, so Ollama / the GPU is never shared across arms.  Run arms one after
another (see ``experiments/paper/analysis/consensus_arms.md``).

    PYTHONPATH=. python -m experiments.paper.runners.run_consensus_arms \
      --config experiments/paper/configs/consensus-arms-pilot.yaml \
      --arm A --run-id pilot_x [--dry-run] [--max-trials N]

Outputs ``<out-root>/<run_id>/arm_<safe_name>/{manifest.json,records.jsonl}``.
Re-invoking the same arm/run-id resumes: trial_ids already in ``records.jsonl``
are skipped.  Trials that fail are logged to ``errors.jsonl`` (not
``records.jsonl``) so a resume retries them.
"""
from __future__ import annotations

import argparse
import copy
import json
import subprocess
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Callable

from experiments.paper.runners.common import (
    BIOLOGY_FIELDS,
    append_jsonl,
    load_yaml_config,
    new_run_id,
    write_json,
)
from experiments.paper.runners.consensus_arms_claims import build_claims_for_trio
from experiments.paper.runners.consensus_arms_classifiers import (
    ClassifierSkipped,
    score_claim,
)
from experiments.paper.runners.consensus_arms_decide import (
    JUDGE_MODEL,
    TRIO_B,
    TRIO_BREF,
    decide_arm_a,
    decide_arm_b,
    decide_arm_c,
    decide_arm_d,
    make_production_batch_merger,
)
from experiments.paper.runners.consensus_arms_io import (
    extractor_outputs_by_model,
    load_biology_trials,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUT_ROOT = REPO_ROOT / "experiments" / "paper" / "results" / "consensus-arms"

ARMS = (
    "A",
    "B",
    "B-ref",
    "C",
    "D:minicheck_ft5",
    "D:hhem",
    "D:bespoke_minicheck_7b",
)
SOLO_MODEL = "gemma4:12b"
DEFAULT_CLASSIFIERS = ("minicheck_ft5", "hhem", "bespoke_minicheck_7b")


class ArmAborted(RuntimeError):
    """Backend-level failure: the whole arm cannot continue."""


class DryRunMismatch(RuntimeError):
    """Existing manifest was produced with a different --dry-run setting."""


def safe_arm_name(arm: str) -> str:
    return arm.replace(":", "_")


def resolve_path(value: str | Path) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else REPO_ROOT / path


def git_sha() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        return out.stdout.strip() or None
    except Exception:
        return None


def arm_models(arm: str, config: dict[str, Any]) -> tuple[str, ...]:
    if arm == "A":
        return (SOLO_MODEL,)
    if arm == "B-ref":
        return tuple(config.get("trio_bref") or TRIO_BREF)
    return tuple(config.get("trio_b") or TRIO_B)


def completed_trial_ids(records_path: Path) -> set[str]:
    done: set[str] = set()
    if not records_path.exists():
        return done
    with records_path.open() as fh:
        for line in fh:
            if not line.strip():
                continue
            try:
                done.add(json.loads(line)["trial_id"])
            except (json.JSONDecodeError, KeyError):
                continue
    return done


def _timed(fn: Callable[[], Any]) -> tuple[Any, float]:
    start = time.perf_counter()
    result = fn()
    return result, time.perf_counter() - start


class ArmContext:
    """Per-invocation state shared by the arm deciders (lazy live wiring)."""

    def __init__(self, *, arm: str, config: dict[str, Any], dry_run: bool, cache_dir: Path):
        self.arm = arm
        self.config = config
        self.dry_run = dry_run
        self.cache_dir = cache_dir
        self.models = arm_models(arm, config)
        self.judge_model = config.get("judge_model") or JUDGE_MODEL
        self.threshold = float(config.get("d_threshold", 0.5))
        self.classifier = arm.split(":", 1)[1] if arm.startswith("D:") else None
        self._handler = None

    def handler(self):
        if self._handler is None:
            from autoannotation import llms

            self._handler = llms.LlmHandler(self.cache_dir)
        return self._handler

    def profile(self, trial: dict[str, Any]):
        if self.dry_run:
            return None
        from autoannotation import organisms

        return organisms.resolve_profile(trial["profile_id"])

    def organism_name(self, trial: dict[str, Any], profile) -> str:
        if profile is not None:
            return profile.canonical_name
        return str(trial.get("profile_id") or "unknown organism")


def _stub_output(candidates: dict[str, dict[str, Any]], models: tuple[str, ...]) -> dict[str, Any]:
    """Dry-run placeholder: first trio candidate passed through unchanged."""
    return copy.deepcopy(candidates[models[0]])


def decide_trial(
    ctx: ArmContext,
    trial: dict[str, Any],
    by_model: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return ``(arm_output, decision_metrics)`` for one trial."""
    arm = ctx.arm
    models = ctx.models
    excerpt = trial.get("excerpt_text")
    gene_id = trial.get("gene_id")
    gene_name = trial.get("gene_name") or ""

    if arm == "A":
        return decide_arm_a(by_model), {"llm_duration_sec": 0.0}

    if arm in ("B", "B-ref"):
        if ctx.dry_run:
            return _stub_output(by_model, models), {"llm_duration_sec": 0.0, "dry_run_stub": True}
        profile = ctx.profile(trial)
        merger = make_production_batch_merger(
            ctx.handler(), model=ctx.judge_model, organism_profile=profile
        )
        (merged, provenance, llm_calls), duration = _timed(
            lambda: decide_arm_b(
                by_model,
                models=models,
                batch_merger=merger,
                expected_gene_id=gene_id,
                expected_name=gene_name,
                organism_profile=profile,
                field_defs_profile=None,
                excerpt=excerpt,
            )
        )
        return merged, {
            "llm_duration_sec": duration,
            "llm_calls": llm_calls,
            "field_provenance": provenance,
        }

    if arm == "C":
        if ctx.dry_run:
            return _stub_output(by_model, models), {"llm_duration_sec": 0.0, "dry_run_stub": True}
        from experiments.paper.runners.consensus_arms_judge_c import make_ollama_judge_fn

        profile = ctx.profile(trial)
        judge_fn = make_ollama_judge_fn(model=ctx.judge_model, organism_profile=profile)
        output, duration = _timed(
            lambda: decide_arm_c(
                by_model,
                models=models,
                judge_fn=judge_fn,
                expected_gene_id=gene_id,
                expected_name=gene_name,
                excerpt=excerpt,
                field_keys=list(BIOLOGY_FIELDS),
            )
        )
        return output, {"llm_duration_sec": duration}

    if ctx.classifier is not None:
        profile = ctx.profile(trial)
        claims = build_claims_for_trio(
            by_model,
            models,
            organism=ctx.organism_name(trial, profile),
            gene_id=str(gene_id),
            gene_name=gene_name,
        )

        def score_all() -> dict[int, float]:
            if ctx.dry_run:
                return {c["claim_index"]: 1.0 for c in claims}
            return {
                c["claim_index"]: score_claim(ctx.classifier, c["text"], excerpt or "")
                for c in claims
            }

        try:
            scores, duration = _timed(score_all)
        except ClassifierSkipped as exc:
            raise ArmAborted(f"classifier {ctx.classifier} skipped: {exc}") from exc
        output = decide_arm_d(
            by_model,
            models=models,
            claims=claims,
            scores_by_claim_id=scores,
            threshold=ctx.threshold,
        )
        metrics: dict[str, Any] = {
            "classifier_duration_sec": duration,
            "classifier": ctx.classifier,
            "threshold": ctx.threshold,
            "n_claims": len(claims),
            "n_supported": sum(1 for s in scores.values() if s >= ctx.threshold),
            # raw per-claim scores so threshold sweeps can be rerun offline
            "claim_scores": [
                {
                    "claim_index": c["claim_index"],
                    "field": c["field"],
                    "source_model": c["source_model"],
                    "source_value": c["source_value"],
                    "text": c["text"],
                    "score": scores.get(c["claim_index"]),
                }
                for c in claims
            ],
        }
        if ctx.dry_run:
            metrics["dry_run_stub"] = True
        return output, metrics

    raise ValueError(f"unknown arm: {arm!r}")


def run_arm(
    *,
    arm: str,
    config: dict[str, Any],
    run_id: str,
    out_root: Path,
    dry_run: bool = False,
    max_trials: int | None = None,
) -> dict[str, Any]:
    arm_dir = out_root / run_id / f"arm_{safe_arm_name(arm)}"
    manifest_path = arm_dir / "manifest.json"
    if manifest_path.exists():
        prior = json.loads(manifest_path.read_text())
        prior_dry = prior.get("dry_run")
        if prior_dry is not dry_run:
            prior_mode = "dry-run" if prior_dry else "live"
            this_mode = "dry-run" if dry_run else "live"
            raise DryRunMismatch(
                f"{manifest_path}: existing run used {prior_mode} mode but this "
                f"invocation uses {this_mode}; pick a new --run-id or match --dry-run"
            )
    records_path = arm_dir / "records.jsonl"
    errors_path = arm_dir / "errors.jsonl"
    source = resolve_path(config["source_records"])
    ctx = ArmContext(arm=arm, config=config, dry_run=dry_run, cache_dir=arm_dir / "llm_cache")

    trials = load_biology_trials(source)
    if max_trials is not None:
        trials = trials[:max_trials]
    done = completed_trial_ids(records_path)

    start = time.perf_counter()
    n_new = n_errors = 0
    status = "complete"
    abort_reason: str | None = None
    for trial in trials:
        trial_id = trial["trial_id"]
        if trial_id in done:
            continue
        try:
            by_model_all = extractor_outputs_by_model(trial)
            missing = [m for m in ctx.models if m not in by_model_all]
            if missing:
                raise KeyError(f"trial lacks extractor outputs for {missing}")
            candidates = {m: by_model_all[m] for m in ctx.models}
            arm_output, metrics = decide_trial(ctx, trial, by_model_all)
        except ArmAborted as exc:
            status, abort_reason = "aborted", str(exc)
            break
        except Exception as exc:  # soft-fail per trial; resume retries it
            n_errors += 1
            append_jsonl(
                errors_path,
                {
                    "trial_id": trial_id,
                    "error": f"{type(exc).__name__}: {exc}",
                    "traceback": traceback.format_exc(),
                },
            )
            continue
        append_jsonl(
            records_path,
            {
                "trial_id": trial_id,
                "excerpt_text": trial.get("excerpt_text"),
                "candidates": candidates,
                "arm_output": arm_output,
                "decision_metrics": metrics,
            },
        )
        done.add(trial_id)
        n_new += 1

    manifest = {
        "experiment_id": config.get("experiment_id"),
        "run_id": run_id,
        "arm": arm,
        "dry_run": dry_run,
        "status": status if n_errors == 0 or status != "complete" else "complete_with_errors",
        "abort_reason": abort_reason,
        "models": list(ctx.models),
        "judge_model": ctx.judge_model if arm in ("B", "B-ref", "C") else None,
        "classifier": ctx.classifier,
        "d_threshold": ctx.threshold if ctx.classifier else None,
        "git_sha": git_sha(),
        "source_records": str(source),
        "n_trials": len(completed_trial_ids(records_path)),
        "n_new": n_new,
        "n_errors": n_errors,
        "duration_sec": time.perf_counter() - start,
    }
    write_json(arm_dir / "manifest.json", manifest)
    return manifest


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--config", required=True, type=Path)
    p.add_argument("--arm", required=True, choices=ARMS)
    p.add_argument("--run-id", default=None)
    p.add_argument("--dry-run", action="store_true", help="no Ollama/classifier calls; stub decisions")
    p.add_argument("--max-trials", type=int, default=None)
    p.add_argument(
        "--out-root",
        "--out",
        dest="out_root",
        type=Path,
        default=DEFAULT_OUT_ROOT,
        help="parent of <run_id>/ (default: experiments/paper/results/consensus-arms)",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.dry_run:
        # Same as run_bias_1_vs_3: pick up OLLAMA host / model tags from worker.env
        # (setdefault, so explicit environment variables still win).
        from autoannotation.worker_env import load_worker_env_into_process

        load_worker_env_into_process()
    config = load_yaml_config(resolve_path(args.config))
    try:
        manifest = run_arm(
            arm=args.arm,
            config=config,
            run_id=args.run_id or new_run_id(),
            out_root=resolve_path(args.out_root),
            dry_run=args.dry_run,
            max_trials=args.max_trials,
        )
    except DryRunMismatch as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(
        f"arm={manifest['arm']} status={manifest['status']} "
        f"trials={manifest['n_trials']} new={manifest['n_new']} errors={manifest['n_errors']}"
    )
    if manifest["status"] == "aborted":
        return 2
    if manifest.get("n_errors", 0) > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
