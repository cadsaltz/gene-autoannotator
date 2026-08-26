from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from experiments.paper.runners.common import (
    CONSENSUS_CONDITION,
    append_jsonl,
    condition_layout_from_manifest,
    load_yaml_config,
    new_run_id,
    stable_json_hash,
    write_aggregate_csv,
    write_json,
)

PAPER_DIR = Path(__file__).resolve().parents[1]
EXPERIMENT_ID = 'cost-benefit-1-vs-3'
CROWD_CONDITION = 'crowd'


def _git_sha() -> str:
    try:
        return subprocess.run(
            ['git', 'rev-parse', 'HEAD'],
            cwd=PAPER_DIR,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return 'unknown'


def _resolve_input_path(path_value: str | Path) -> Path:
    path = Path(path_value)
    if path.is_absolute():
        return path
    cwd_candidate = Path.cwd() / path
    if cwd_candidate.exists():
        return cwd_candidate
    return PAPER_DIR / path


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    records = []
    for line in path.read_text().splitlines():
        if line.strip():
            records.append(json.loads(line))
    return records


def _load_bias_records(bias_run_dir: Path) -> list[dict[str, Any]]:
    records_path = bias_run_dir / 'records.jsonl'
    if not records_path.is_file():
        raise FileNotFoundError(f'bias records.jsonl missing: {records_path}')
    return _load_jsonl(records_path)


def _load_trial_observables(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    observables = [
        record for record in records if record.get('record_type') == 'trial_observable'
    ]
    if not observables:
        raise ValueError('no trial_observable rows in bias records.jsonl')
    return observables


def _load_field_scores(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        record for record in records if record.get('record_type') == 'field_score'
    ]


def _rate(scores: list[dict[str, Any]], label: str) -> float:
    denominator_scores = (
        scores
        if label == 'null'
        else [record for record in scores if record['groundedness_label'] != 'null']
    )
    if not denominator_scores:
        return 0.0
    return (
        sum(record['groundedness_label'] == label for record in denominator_scores)
        / len(denominator_scores)
    )


def _metric_value(metrics: dict[str, Any] | None, key: str) -> float | int | None:
    if not metrics:
        return None
    value = metrics.get(key)
    if value is None:
        return None
    return value


def _usage_value(metrics: dict[str, Any] | None, key: str) -> int | None:
    usage = (metrics or {}).get('usage')
    if not usage:
        return None
    value = usage.get(key)
    if value is None:
        return None
    return int(value)


def _aggregate_rows(
    field_scores: list[dict[str, Any]],
    observables: list[dict[str, Any]],
    *,
    layout: dict[str, Any],
    include_extractors: bool = True,
) -> list[dict[str, Any]]:
    primary_conditions = layout['single_conditions'] + (CROWD_CONDITION, CONSENSUS_CONDITION)
    extractor_conditions = layout['extractor_conditions']
    crowd_conditions = layout['crowd_conditions']
    conditions = (
        primary_conditions + extractor_conditions
        if include_extractors
        else primary_conditions
    )
    rows = []
    for condition in conditions:
        score_condition = CONSENSUS_CONDITION if condition == CROWD_CONDITION else condition
        condition_scores = [
            record for record in field_scores if record['condition'] == score_condition
        ]
        durations: list[float] = []
        calls: list[int] = []
        tokens: list[int] = []
        for observable in observables:
            metrics_by_condition = observable.get('condition_metrics') or {}
            cost_conditions = crowd_conditions if condition == CROWD_CONDITION else (condition,)
            condition_metrics = [
                metrics_by_condition.get(cost_condition)
                for cost_condition in cost_conditions
            ]
            duration_values = [
                _metric_value(metrics, 'duration_sec') for metrics in condition_metrics
            ]
            if all(value is not None for value in duration_values):
                durations.append(sum(float(value) for value in duration_values))
            call_values = [
                _usage_value(metrics, 'calls') for metrics in condition_metrics
            ]
            if all(value is not None for value in call_values):
                calls.append(sum(int(value) for value in call_values))
            token_values = [
                _usage_value(metrics, 'known_total_tokens')
                for metrics in condition_metrics
            ]
            if all(value is not None for value in token_values):
                tokens.append(sum(int(value) for value in token_values))

        rows.append({
            'condition': condition,
            'model': next(
                (
                    (observable.get('condition_metrics') or {}).get(condition, {}).get('model')
                    for observable in observables
                    if (observable.get('condition_metrics') or {}).get(condition, {}).get('model')
                ),
                None,
            ),
            'unsupported_rate': _rate(condition_scores, 'unsupported'),
            'supported_rate': _rate(condition_scores, 'supported'),
            'null_rate': _rate(condition_scores, 'null'),
            'wall_time_sec_total': sum(durations) if durations else 0.0,
            'wall_time_sec_mean': (
                sum(durations) / len(durations) if durations else 0.0
            ),
            'llm_calls': sum(calls) if calls else 0,
            'known_total_tokens': sum(tokens) if tokens else 0,
            'n_field_values': len(condition_scores),
        })
    return rows


def _crowd_wall_time_per_trial(
    observable: dict[str, Any],
    *,
    crowd_conditions: tuple[str, ...],
) -> float | None:
    metrics_by_condition = observable.get('condition_metrics') or {}
    durations: list[float] = []
    for condition in crowd_conditions:
        metrics = metrics_by_condition.get(condition)
        duration = _metric_value(metrics, 'duration_sec')
        if duration is None:
            return None
        durations.append(float(duration))
    return sum(durations)


def verify_crowd_timing(
    observables: list[dict[str, Any]],
    *,
    crowd_conditions: tuple[str, ...],
) -> dict[str, Any]:
    """Return crowd-vs-single wall-time check (None durations skipped)."""
    violations = []
    checked_trials = 0
    for observable in observables:
        crowd_time = _crowd_wall_time_per_trial(
            observable,
            crowd_conditions=crowd_conditions,
        )
        if crowd_time is None:
            continue
        checked_trials += 1
        metrics_by_condition = observable.get('condition_metrics') or {}
        for condition in observable.get('outputs', {}):
            if not str(condition).startswith('single_'):
                continue
            duration = _metric_value(
                metrics_by_condition.get(condition), 'duration_sec',
            )
            if duration is None:
                continue
            if crowd_time <= float(duration):
                violations.append({
                    'trial_id': observable['trial_id'],
                    'crowd_wall_time_sec': crowd_time,
                    'single_condition': condition,
                    'single_wall_time_sec': float(duration),
                })
    return {
        'checked_trials': checked_trials,
        'violations': violations,
        'passed': not violations,
    }


def derive_cost_benefit_1_vs_3(
    *,
    bias_run_dir: Path,
    run_id: str | None = None,
    config_path: Path | None = None,
    include_extractors: bool = True,
) -> Path:
    bias_run_dir = Path(bias_run_dir)
    if not bias_run_dir.is_dir():
        raise FileNotFoundError(f'bias run dir missing: {bias_run_dir}')

    parent_manifest_path = bias_run_dir / 'manifest.json'
    if not parent_manifest_path.is_file():
        raise FileNotFoundError(f'bias manifest.json missing: {parent_manifest_path}')
    parent_manifest = json.loads(parent_manifest_path.read_text())

    config_path = config_path or (PAPER_DIR / 'configs' / 'cost-benefit-1-vs-3.yaml')
    config = load_yaml_config(config_path)
    if config.get('experiment_id') != EXPERIMENT_ID:
        raise ValueError(
            f'expected experiment_id {EXPERIMENT_ID!r}, got {config.get("experiment_id")!r}',
        )

    layout = condition_layout_from_manifest(parent_manifest)
    primary_conditions = layout['single_conditions'] + (CROWD_CONDITION, CONSENSUS_CONDITION)
    crowd_conditions = layout['crowd_conditions']

    records = _load_bias_records(bias_run_dir)
    observables = _load_trial_observables(records)
    field_scores = _load_field_scores(records)
    aggregate_rows = _aggregate_rows(
        field_scores,
        observables,
        layout=layout,
        include_extractors=include_extractors,
    )
    timing_check = verify_crowd_timing(
        observables,
        crowd_conditions=crowd_conditions,
    )

    run_id = run_id or new_run_id()
    output_dir = PAPER_DIR / 'results' / EXPERIMENT_ID / run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    records_path = output_dir / 'records.jsonl'
    records_path.write_text('')

    for row in aggregate_rows:
        append_jsonl(records_path, {
            'record_type': 'condition_summary',
            **row,
        })

    manifest = {
        'experiment_id': EXPERIMENT_ID,
        'run_id': run_id,
        'derived': True,
        'git_sha': _git_sha(),
        'config_path': str(config_path),
        'config_hash': stable_json_hash(config),
        'parent_experiment_id': parent_manifest.get('experiment_id'),
        'parent_bias_run_id': parent_manifest.get('run_id'),
        'parent_bias_run_path': str(bias_run_dir.resolve()),
        'parent_manifest_hash': stable_json_hash(parent_manifest),
        'n_trials': len(observables),
        'n_field_scores': len(field_scores),
        'conditions': [
            row['condition'] for row in aggregate_rows
        ],
        'primary_conditions': list(primary_conditions),
        'crowd_conditions': list(crowd_conditions),
        'crowd_timing_check': timing_check,
        'timestamp': datetime.now(timezone.utc).isoformat(),
    }
    write_json(output_dir / 'manifest.json', manifest)
    write_aggregate_csv(output_dir / 'aggregate.csv', aggregate_rows)
    return output_dir


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description='Derive joint quality×cost table from a bias-1-vs-3-small run.',
    )
    parser.add_argument(
        '--bias-run-dir',
        type=Path,
        required=True,
        help='Path to a bias-1-vs-3-small run directory containing records.jsonl',
    )
    parser.add_argument('--run-id', help='Output run id (default: UTC timestamp)')
    parser.add_argument(
        '--config',
        type=Path,
        default=PAPER_DIR / 'configs' / 'cost-benefit-1-vs-3.yaml',
        help='cost-benefit-1-vs-3 config path',
    )
    parser.add_argument(
        '--primary-only',
        action='store_true',
        help='Omit extractor_A/B/C rows from aggregate',
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    bias_run_dir = _resolve_input_path(args.bias_run_dir)
    config_path = _resolve_input_path(args.config)
    output_dir = derive_cost_benefit_1_vs_3(
        bias_run_dir=bias_run_dir,
        run_id=args.run_id,
        config_path=config_path,
        include_extractors=not args.primary_only,
    )
    print(output_dir)


if __name__ == '__main__':
    main()
