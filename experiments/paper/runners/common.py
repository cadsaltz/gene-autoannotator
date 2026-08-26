from __future__ import annotations

import csv
import hashlib
import json
import random
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

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

GENERAL_CATEGORIES = frozenset({'truthful', 'grounded', 'trap'})


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


def infer_trial_pool(item: dict[str, Any]) -> str:
    category = item.get('category')
    if category in GENERAL_CATEGORIES or 'focus_question' in item:
        return 'general'
    return 'biology'


def load_experiment_items(
    fixture_config: dict[str, Any],
    *,
    fixture_path: Callable[[str], Path],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    fixture_documents: dict[str, Any] = {}
    items: list[dict[str, Any]] = []

    papers_path = fixture_config.get('papers')
    if papers_path:
        path = fixture_path(papers_path)
        document = json.loads(path.read_text())
        fixture_documents['papers'] = document
        items.extend(
            {**item, 'trial_pool': 'biology'}
            for item in load_paper_snapshot_fixture(path)
        )

    general_path = fixture_config.get('general')
    if general_path:
        path = fixture_path(general_path)
        document = json.loads(path.read_text())
        fixture_documents['general'] = document
        items.extend(
            {**item, 'trial_pool': 'general'}
            for item in load_paper_snapshot_fixture(path)
        )

    if not items:
        raise ValueError('fixtures must include papers and/or general')

    genes_path = fixture_config.get('genes')
    if genes_path:
        fixture_documents['genes'] = json.loads(fixture_path(genes_path).read_text())

    return items, fixture_documents


def extraction_fields_from_manifest(manifest: dict[str, Any]) -> tuple[str, ...]:
    fields = manifest.get('extraction_fields')
    if fields:
        return tuple(str(field) for field in fields)
    return BIOLOGY_FIELDS


def field_kinds_from_manifest(
    manifest: dict[str, Any],
    *,
    default: dict[str, str],
) -> dict[str, str]:
    kinds = manifest.get('field_kinds')
    if kinds:
        return {str(key): str(value) for key, value in kinds.items()}
    return default


CONSENSUS_CONDITION = 'consensus_D'


def extractor_slot_label(index: int) -> str:
    if index < 26:
        return chr(ord('A') + index)
    return str(index + 1)


def build_condition_layout(extractor_models: list[str]) -> dict[str, Any]:
    if len(extractor_models) < 2:
        raise ValueError(
            f'models.extractors must contain at least two model tags, got {len(extractor_models)}',
        )
    labels = [extractor_slot_label(index) for index in range(len(extractor_models))]
    extractor_conditions = tuple(f'extractor_{label}' for label in labels)
    single_conditions = tuple(f'single_{label}' for label in labels)
    conditions = extractor_conditions + (CONSENSUS_CONDITION,) + single_conditions
    condition_models: dict[str, str] = {}
    for label, model in zip(labels, extractor_models):
        condition_models[f'extractor_{label}'] = model
        condition_models[f'single_{label}'] = model
    return {
        'labels': labels,
        'conditions': conditions,
        'extractor_conditions': extractor_conditions,
        'single_conditions': single_conditions,
        'consensus_condition': CONSENSUS_CONDITION,
        'crowd_conditions': extractor_conditions + (CONSENSUS_CONDITION,),
        'primary_conditions': single_conditions + (CONSENSUS_CONDITION,),
        'condition_models': condition_models,
    }


def layout_from_conditions(
    conditions: list[str] | tuple[str, ...],
    *,
    condition_models: dict[str, str] | None = None,
) -> dict[str, Any]:
    extractor_conditions = tuple(
        condition for condition in conditions if condition.startswith('extractor_')
    )
    single_conditions = tuple(
        condition for condition in conditions if condition.startswith('single_')
    )
    if len(extractor_conditions) < 2:
        raise ValueError(
            f'conditions must include at least two extractor_* entries, got {extractor_conditions!r}',
        )
    labels = [condition.removeprefix('extractor_') for condition in extractor_conditions]
    return {
        'labels': labels,
        'conditions': tuple(conditions),
        'extractor_conditions': extractor_conditions,
        'single_conditions': single_conditions,
        'consensus_condition': CONSENSUS_CONDITION,
        'crowd_conditions': extractor_conditions + (CONSENSUS_CONDITION,),
        'primary_conditions': single_conditions + (CONSENSUS_CONDITION,),
        'condition_models': dict(condition_models or {}),
    }


def conditions_from_manifest(manifest: dict[str, Any]) -> tuple[str, ...]:
    conditions = manifest.get('conditions')
    if conditions:
        return tuple(str(condition) for condition in conditions)
    extractors = (manifest.get('model_tags') or {}).get('extractors') or ()
    return build_condition_layout(list(extractors))['conditions']


def extractor_conditions_from_manifest(manifest: dict[str, Any]) -> tuple[str, ...]:
    extractors = (manifest.get('model_tags') or {}).get('extractors') or ()
    return build_condition_layout(list(extractors))['extractor_conditions']


def condition_layout_from_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    stored_conditions = manifest.get('conditions')
    stored_models = manifest.get('condition_models') or {}
    extractors = list((manifest.get('model_tags') or {}).get('extractors') or ())
    if stored_conditions:
        layout = layout_from_conditions(stored_conditions, condition_models=stored_models)
    elif len(extractors) >= 2:
        layout = build_condition_layout(extractors)
    else:
        layout = build_condition_layout(['unknown-a', 'unknown-b', 'unknown-c'])
    consensus_model = (manifest.get('model_tags') or {}).get('consensus')
    if consensus_model:
        layout = dict(layout)
        models = dict(layout['condition_models'])
        models[CONSENSUS_CONDITION] = consensus_model
        layout['condition_models'] = models
    return layout


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
