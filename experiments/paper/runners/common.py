from __future__ import annotations

import csv
import hashlib
import json
import random
from collections import defaultdict
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

PROFILE_ALIASES = {
    'mtb': 'mtb-h37rv',
    'ecoli': 'ecoli-k12-mg1655',
    'e-coli': 'ecoli-k12-mg1655',
    'tcruzi': 'tcruzi-clbrener',
    't-cruzi': 'tcruzi-clbrener',
}


def resolve_profile_id(value: str) -> str:
    return PROFILE_ALIASES.get(value.strip().lower(), value.strip())


def parse_distribution(
    raw: str | dict[str, int] | list[str] | None,
) -> dict[str, int] | None:
    if raw is None:
        return None
    if isinstance(raw, dict):
        return {resolve_profile_id(key): int(value) for key, value in raw.items()}
    specs: list[str]
    if isinstance(raw, str):
        specs = [part.strip() for part in raw.split(',') if part.strip()]
    else:
        specs = [str(part).strip() for part in raw if str(part).strip()]
    if not specs:
        return None
    parsed: dict[str, int] = {}
    for spec in specs:
        if ':' not in spec:
            raise ValueError(f'distribution entry must be profile:count, got {spec!r}')
        profile, count_text = spec.split(':', 1)
        parsed[resolve_profile_id(profile)] = int(count_text.strip())
    return parsed


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


def _group_by_profile(items: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        grouped[item['profile_id']].append(item)
    return dict(grouped)


def select_trials(
    items: list[dict[str, Any]],
    n_trials: int,
    *,
    distribution: dict[str, int] | None = None,
    seed: int | None = None,
    max_trials: int | None = None,
) -> list[dict[str, Any]]:
    if n_trials < 1:
        raise ValueError(f'n_trials must be >= 1, got {n_trials}')
    pool_cap = max_trials if max_trials is not None else len(items)
    if n_trials > pool_cap:
        raise ValueError(f'n_trials={n_trials} exceeds allowed maximum {pool_cap}')
    if n_trials > len(items):
        raise ValueError(f'n_trials={n_trials} exceeds fixture pool size {len(items)}')

    if distribution:
        expected = sum(distribution.values())
        if expected != n_trials:
            raise ValueError(
                f'distribution counts sum to {expected} but n_trials={n_trials}'
            )
        grouped = _group_by_profile(items)
        rng = random.Random(seed)
        selected: list[dict[str, Any]] = []
        for profile_id in sorted(distribution):
            count = distribution[profile_id]
            pool = list(grouped.get(profile_id, []))
            if count > len(pool):
                raise ValueError(
                    f'distribution requests {count} trials for {profile_id} '
                    f'but fixture only has {len(pool)}'
                )
            rng.shuffle(pool)
            selected.extend(pool[:count])
        selected.sort(key=lambda item: item.get('trial_id', ''))
        return selected

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
