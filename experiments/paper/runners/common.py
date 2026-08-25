from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

BIOLOGY_FIELDS = (
    'function',
    'functional_category',
    'drug_susc_impact',
    'infection_impact',
    'essential_in_vitro',
    'essential_in_vivo',
)

MAX_TRIALS = 15


def load_yaml_config(path: Path) -> dict[str, Any]:
    with path.open() as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f'config must be a mapping: {path}')
    return data


def load_paper_snapshot_fixture(path: Path) -> list[dict[str, Any]]:
    with path.open() as f:
        data = json.load(f)
    items = data.get('items')
    if not isinstance(items, list) or len(items) < 1:
        raise ValueError(f'fixture items missing: {path}')
    return items


def select_trials(items: list[dict[str, Any]], n_trials: int) -> list[dict[str, Any]]:
    if n_trials < 1 or n_trials > MAX_TRIALS:
        raise ValueError(f'n_trials must be in 1..{MAX_TRIALS}, got {n_trials}')
    if n_trials > len(items):
        raise ValueError(f'n_trials={n_trials} exceeds fixture pool size {len(items)}')
    return list(items[:n_trials])


def stable_json_hash(obj: Any) -> str:
    blob = json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


def new_run_id() -> str:
    return datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')


def is_nullish(value: Any) -> bool:
    try:
        from autoannotation import llms
        return llms.is_unknown_value(value)
    except Exception:
        if value is None:
            return True
        if isinstance(value, str) and value.strip().lower() in {'', 'null', 'none', 'unknown', 'n/a'}:
            return True
        return False


def field_values_equal(a: Any, b: Any, *, kind: str) -> bool:
    if is_nullish(a) and is_nullish(b):
        return True
    if is_nullish(a) or is_nullish(b):
        return False
    if kind == 'boolean':
        return bool(a) is bool(b)
    if kind == 'array':
        left = {str(x).strip().lower() for x in a if isinstance(x, str) and x.strip()}
        right = {str(x).strip().lower() for x in b if isinstance(x, str) and x.strip()}
        return left == right
    return ' '.join(str(a).lower().split()) == ' '.join(str(b).lower().split())


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False, default=str) + '\n')


def append_jsonl(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a') as f:
        f.write(json.dumps(obj, ensure_ascii=False, default=str) + '\n')


def write_aggregate_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text('')
        return
    fieldnames = list(rows[0].keys())
    with path.open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
