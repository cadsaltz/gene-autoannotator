from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from experiments.paper.runners.common import (
    append_jsonl,
    condition_layout_from_manifest,
    extraction_fields_from_manifest,
    field_kinds_from_manifest,
    load_yaml_config,
    new_run_id,
    stable_json_hash,
    write_aggregate_csv,
    write_json,
)
from experiments.paper.runners.split_classify import classify_extractor_split

PAPER_DIR = Path(__file__).resolve().parents[1]
EXPERIMENT_ID = 'split-vs-not'

FIELD_KINDS = {
    'function': 'string',
    'functional_category': 'array',
    'drug_susc_impact': 'string',
    'infection_impact': 'string',
    'essential_in_vitro': 'boolean',
    'essential_in_vivo': 'boolean',
}


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


def _load_trial_observables(bias_run_dir: Path) -> list[dict[str, Any]]:
    records_path = bias_run_dir / 'records.jsonl'
    if not records_path.is_file():
        raise FileNotFoundError(f'bias records.jsonl missing: {records_path}')
    observables = [
        record for record in _load_jsonl(records_path)
        if record.get('record_type') == 'trial_observable'
    ]
    if not observables:
        raise ValueError(f'no trial_observable rows in {records_path}')
    return observables


def _extract_value(output: Any, field: str) -> Any:
    if not isinstance(output, dict):
        return None
    return output.get(field)


def _field_split_records(
    observable: dict[str, Any],
    *,
    fields: tuple[str, ...],
    field_kinds: dict[str, str],
    extractor_conditions: tuple[str, ...],
) -> list[dict[str, Any]]:
    outputs = observable.get('outputs') or {}
    records = []
    for field in fields:
        extractor_values = {
            condition: _extract_value(outputs.get(condition), field)
            for condition in extractor_conditions
        }
        split_class = classify_extractor_split(
            extractor_values,
            kind=field_kinds[field],
        )
        records.append({
            'record_type': 'field_split',
            'trial_id': observable['trial_id'],
            'profile_id': observable.get('profile_id'),
            'gene_id': observable.get('gene_id'),
            'gene_name': observable.get('gene_name'),
            'pmc_id': observable.get('pmc_id'),
            'section': observable.get('section'),
            'field': field,
            'field_kind': field_kinds[field],
            'split_class': split_class,
            'extractor_values': extractor_values,
        })
    return records


def _rate(counts: dict[str, int], label: str) -> float:
    total = sum(counts.values())
    if total == 0:
        return 0.0
    return counts.get(label, 0) / total


def _aggregate_rows(
    split_records: list[dict[str, Any]],
    *,
    fields: tuple[str, ...],
) -> list[dict[str, Any]]:
    rows = []

    def counts_for(records: list[dict[str, Any]]) -> dict[str, int]:
        result = {'split': 0, 'unanimous': 0, 'partial': 0}
        for record in records:
            result[record['split_class']] += 1
        return result

    overall_counts = counts_for(split_records)
    rows.append({
        'scope': 'overall',
        'field': '',
        'n_field_values': len(split_records),
        'split_rate': _rate(overall_counts, 'split'),
        'unanimous_rate': _rate(overall_counts, 'unanimous'),
        'partial_rate': _rate(overall_counts, 'partial'),
    })

    for field in fields:
        field_records = [record for record in split_records if record['field'] == field]
        field_counts = counts_for(field_records)
        rows.append({
            'scope': 'field',
            'field': field,
            'n_field_values': len(field_records),
            'split_rate': _rate(field_counts, 'split'),
            'unanimous_rate': _rate(field_counts, 'unanimous'),
            'partial_rate': _rate(field_counts, 'partial'),
        })
    return rows


def derive_split_vs_not(
    *,
    bias_run_dir: Path,
    run_id: str | None = None,
    config_path: Path | None = None,
) -> Path:
    bias_run_dir = Path(bias_run_dir)
    if not bias_run_dir.is_dir():
        raise FileNotFoundError(f'bias run dir missing: {bias_run_dir}')

    parent_manifest_path = bias_run_dir / 'manifest.json'
    if not parent_manifest_path.is_file():
        raise FileNotFoundError(f'bias manifest.json missing: {parent_manifest_path}')
    parent_manifest = json.loads(parent_manifest_path.read_text())
    layout = condition_layout_from_manifest(parent_manifest)
    extraction_fields = extraction_fields_from_manifest(parent_manifest)
    field_kinds = field_kinds_from_manifest(parent_manifest, default=FIELD_KINDS)
    extractor_conditions = layout['extractor_conditions']
    for field in extraction_fields:
        if field not in field_kinds:
            field_kinds[field] = 'string'

    config_path = config_path or (PAPER_DIR / 'configs' / 'split-vs-not.yaml')
    config = load_yaml_config(config_path)
    if config.get('experiment_id') != EXPERIMENT_ID:
        raise ValueError(f'expected experiment_id {EXPERIMENT_ID!r}, got {config.get("experiment_id")!r}')

    run_id = run_id or new_run_id()
    output_dir = PAPER_DIR / 'results' / EXPERIMENT_ID / run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    records_path = output_dir / 'records.jsonl'
    records_path.write_text('')

    observables = _load_trial_observables(bias_run_dir)
    split_records = []
    for observable in observables:
        trial_records = _field_split_records(
            observable,
            fields=extraction_fields,
            field_kinds=field_kinds,
            extractor_conditions=extractor_conditions,
        )
        split_records.extend(trial_records)
        for record in trial_records:
            append_jsonl(records_path, record)

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
        'extraction_fields': list(extraction_fields),
        'n_trials': len(observables),
        'n_field_values': len(split_records),
        'timestamp': datetime.now(timezone.utc).isoformat(),
    }
    write_json(output_dir / 'manifest.json', manifest)
    write_aggregate_csv(
        output_dir / 'aggregate.csv',
        _aggregate_rows(split_records, fields=extraction_fields),
    )
    return output_dir


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description='Derive split-vs-not field classifications from a bias run.',
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
        default=PAPER_DIR / 'configs' / 'split-vs-not.yaml',
        help='split-vs-not config path',
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    bias_run_dir = _resolve_input_path(args.bias_run_dir)
    config_path = _resolve_input_path(args.config)
    output_dir = derive_split_vs_not(
        bias_run_dir=bias_run_dir,
        run_id=args.run_id,
        config_path=config_path,
    )
    print(output_dir)


if __name__ == '__main__':
    main()
