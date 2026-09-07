from __future__ import annotations

import argparse
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from experiments.paper.general_extraction import (
    GENERAL_EXTRACTION_FIELDS,
    GENERAL_FIELD_KINDS,
    get_llm_general_consensus_json,
    get_llm_general_extraction_json,
)
from experiments.paper.runners.common import (
    BIOLOGY_FIELDS,
    CONSENSUS_CONDITION,
    append_jsonl,
    build_condition_layout,
    load_experiment_items,
    load_yaml_config,
    new_run_id,
    parse_distribution,
    select_trials,
    stable_json_hash,
    validate_distribution,
    write_aggregate_csv,
    write_json,
)

PAPER_DIR = Path(__file__).resolve().parents[1]
ALLOWED_EXPERIMENT_IDS = frozenset({'bias-1-vs-3-small', 'bias-general-1-vs-3'})
DEFAULT_CONDITION_LAYOUT = build_condition_layout([
    'model-a',
    'model-b',
    'model-c',
])
CONDITIONS = DEFAULT_CONDITION_LAYOUT['conditions']


def _fixture_path(path_value: str) -> Path:
    path = Path(path_value)
    return path if path.is_absolute() else PAPER_DIR / path


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


def _as_json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, dict):
        raise TypeError(f'LLM output must be a JSON object, got {type(value).__name__}')
    return value


def _usage_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    known_tokens = [
        record.get('total_tokens')
        for record in records
        if record.get('total_tokens') is not None
    ]
    return {
        'calls': len(records),
        'cache_hits': sum(bool(record.get('cache_hit')) for record in records),
        'known_total_tokens': sum(known_tokens),
        'token_usage_complete': len(known_tokens) == len(records),
        'records': records,
    }


def _timed_handler_call(handler: Any, call: Callable[[], tuple[Any, float]]):
    usage_start = len(handler.usage_records)
    wall_start = time.perf_counter()
    output, llm_duration = call()
    wall_duration = time.perf_counter() - wall_start
    usage = _usage_summary(handler.usage_records[usage_start:])
    return _as_json_object(output), {
        'duration_sec': wall_duration,
        'llm_duration_sec': llm_duration,
        'usage': usage,
    }


def _empty_metrics() -> dict[str, Any]:
    return {
        'duration_sec': None,
        'llm_duration_sec': None,
        'model': None,
        'usage': None,
    }


def _empty_observable(
    trial: dict[str, Any],
    *,
    conditions: tuple[str, ...],
) -> dict[str, Any]:
    observable: dict[str, Any] = {
        'record_type': 'trial_observable',
        'trial_id': trial['trial_id'],
        'fixture_trial_id': trial.get('fixture_trial_id', trial['trial_id']),
        'trial_pool': trial['trial_pool'],
        'profile_id': trial['profile_id'],
        'section': trial['section'],
        'excerpt_text': trial['excerpt_text'],
        'outputs': {condition: None for condition in conditions},
        'condition_metrics': {
            condition: _empty_metrics() for condition in conditions
        },
        'prompts': {},
    }
    if trial.get('excerpt_preparation') is not None:
        observable['excerpt_preparation'] = trial['excerpt_preparation']
    if trial.get('source_excerpt_chars') is not None:
        observable['source_excerpt_chars'] = trial['source_excerpt_chars']
    if trial['trial_pool'] == 'biology':
        observable.update({
            'gene_id': trial['gene_id'],
            'gene_name': trial['gene_name'],
            'pmc_id': trial.get('pmc_id'),
        })
    else:
        observable.update({
            'category': trial['category'],
            'source_id': trial['source_id'],
            'focus_question': trial['focus_question'],
        })
    return observable


def _attach_metrics(
    metrics: dict[str, Any],
    *,
    model: str | None,
) -> dict[str, Any]:
    enriched = dict(metrics)
    enriched['model'] = model
    return enriched


def _biology_excerpts_for_trial(trial: dict[str, Any]):
    from autoannotation.section_excerpt_router import prepare_section_excerpts

    return prepare_section_excerpts(
        trial['section'],
        trial['excerpt_text'],
        gene_id=trial['gene_id'],
        gene_name=trial['gene_name'],
    )


def _run_trial_id(fixture_id: str, part, *, index: int, part_count: int) -> str:
    if part_count == 1:
        return fixture_id
    if '#' in part.label:
        suffix = part.label.split('#', 1)[1]
    else:
        suffix = str(index + 1)
    return f'{fixture_id}#{suffix}'


def expand_trials_for_excerpts(fixture_trials: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Expand fixture selections into one run trial per excerpt part (chunk/grep/pass)."""
    expanded: list[dict[str, Any]] = []
    for trial in fixture_trials:
        if trial['trial_pool'] != 'biology':
            run_trial = dict(trial)
            run_trial['fixture_trial_id'] = trial['trial_id']
            expanded.append(run_trial)
            continue

        parts = _biology_excerpts_for_trial(trial)
        fixture_id = trial['trial_id']
        source_chars = len(trial['excerpt_text'])
        for index, part in enumerate(parts):
            run_trial = dict(trial)
            run_trial['fixture_trial_id'] = fixture_id
            run_trial['trial_id'] = _run_trial_id(
                fixture_id, part, index=index, part_count=len(parts),
            )
            run_trial['section'] = part.label
            run_trial['excerpt_text'] = part.text
            run_trial['excerpt_preparation'] = {
                'tier': part.tier,
                'part_index': index + 1,
                'part_count': len(parts),
                'chars': len(part.text),
            }
            if len(parts) > 1:
                run_trial['source_excerpt_chars'] = source_chars
            expanded.append(run_trial)
    return expanded


def _collect_prompts_from_handlers(
    crowd_handler: Any,
    single_handlers: dict[str, Any],
    *,
    layout: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    prompts: dict[str, dict[str, Any]] = {}
    crowd_records = list(crowd_handler.prompt_records)
    crowd_index = 0

    for label in layout['labels']:
        condition = f'extractor_{label}'
        if crowd_index < len(crowd_records):
            prompts[condition] = crowd_records[crowd_index]
            crowd_index += 1

    for record in crowd_records[crowd_index:]:
        if record.get('role') == 'section_consensus':
            prompts[CONSENSUS_CONDITION] = record
            break

    for label in layout['labels']:
        condition = f'single_{label}'
        handler = single_handlers[condition]
        if handler.prompt_records:
            prompts[condition] = handler.prompt_records[-1]

    return prompts


def _collect_general_prompts_from_handlers(
    crowd_handler: Any,
    single_handlers: dict[str, Any],
    *,
    layout: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    prompts: dict[str, dict[str, Any]] = {}
    crowd_records = list(crowd_handler.prompt_records)
    crowd_index = 0

    for label in layout['labels']:
        condition = f'extractor_{label}'
        if crowd_index < len(crowd_records):
            prompts[condition] = crowd_records[crowd_index]
            crowd_index += 1

    for record in crowd_records[crowd_index:]:
        if record.get('role') == 'general_consensus':
            prompts[CONSENSUS_CONDITION] = record
            break

    for label in layout['labels']:
        condition = f'single_{label}'
        handler = single_handlers[condition]
        if handler.prompt_records:
            prompts[condition] = handler.prompt_records[-1]

    return prompts


def _run_biology_trial(
    trial: dict[str, Any],
    *,
    layout: dict[str, Any],
    consensus_model: str,
    cache_root: Path,
) -> dict[str, Any]:
    from autoannotation import llms, organisms

    profile = organisms.resolve_profile(trial['profile_id'])
    observable = _empty_observable(trial, conditions=layout['conditions'])
    crowd_handler = llms.LlmHandler(cache_root / 'crowd')
    crowd_handler.prompt_records = []
    single_handlers: dict[str, Any] = {}
    candidates = []

    for label in layout['labels']:
        model = layout['condition_models'][f'extractor_{label}']
        condition = f'extractor_{label}'
        output, metrics = _timed_handler_call(
            crowd_handler,
            lambda model=model: crowd_handler.get_llm_gene_info_json(
                trial['gene_id'],
                trial['gene_name'],
                trial['excerpt_text'],
                model,
                section_type=trial['section'],
                organism_profile=profile,
            ),
        )
        candidates.append(output)
        observable['outputs'][condition] = output
        observable['condition_metrics'][condition] = _attach_metrics(metrics, model=model)

    consensus, metrics = _timed_handler_call(
        crowd_handler,
        lambda: crowd_handler.get_llm_consensus_json(
            candidates,
            excerpt=trial['excerpt_text'],
            expected_gene_id=trial['gene_id'],
            expected_name=trial['gene_name'],
            model=consensus_model,
            section_type=trial['section'],
            organism_profile=profile,
        ),
    )
    observable['outputs'][CONSENSUS_CONDITION] = consensus
    observable['condition_metrics'][CONSENSUS_CONDITION] = _attach_metrics(
        metrics,
        model=consensus_model,
    )

    for label in layout['labels']:
        model = layout['condition_models'][f'single_{label}']
        condition = f'single_{label}'
        handler = llms.LlmHandler(cache_root / condition)
        handler.prompt_records = []
        single_handlers[condition] = handler
        output, metrics = _timed_handler_call(
            handler,
            lambda handler=handler, model=model: handler.get_llm_gene_info_json(
                trial['gene_id'],
                trial['gene_name'],
                trial['excerpt_text'],
                model,
                section_type=trial['section'],
                organism_profile=profile,
            ),
        )
        observable['outputs'][condition] = output
        observable['condition_metrics'][condition] = _attach_metrics(metrics, model=model)

    observable['prompts'] = _collect_prompts_from_handlers(
        crowd_handler,
        single_handlers,
        layout=layout,
    )
    return observable


def _run_general_trial(
    trial: dict[str, Any],
    *,
    layout: dict[str, Any],
    consensus_model: str,
    cache_root: Path,
) -> dict[str, Any]:
    from autoannotation import llms

    observable = _empty_observable(trial, conditions=layout['conditions'])
    crowd_handler = llms.LlmHandler(cache_root / 'crowd')
    crowd_handler.prompt_records = []
    single_handlers: dict[str, Any] = {}
    candidates = []

    for label in layout['labels']:
        model = layout['condition_models'][f'extractor_{label}']
        condition = f'extractor_{label}'
        output, metrics = _timed_handler_call(
            crowd_handler,
            lambda model=model: get_llm_general_extraction_json(
                crowd_handler,
                excerpt=trial['excerpt_text'],
                focus_question=trial['focus_question'],
                model=model,
            ),
        )
        candidates.append(output)
        observable['outputs'][condition] = output
        observable['condition_metrics'][condition] = _attach_metrics(metrics, model=model)

    consensus, metrics = _timed_handler_call(
        crowd_handler,
        lambda: get_llm_general_consensus_json(
            crowd_handler,
            candidates,
            excerpt=trial['excerpt_text'],
            model=consensus_model,
        ),
    )
    observable['outputs'][CONSENSUS_CONDITION] = consensus
    observable['condition_metrics'][CONSENSUS_CONDITION] = _attach_metrics(
        metrics,
        model=consensus_model,
    )

    for label in layout['labels']:
        model = layout['condition_models'][f'single_{label}']
        condition = f'single_{label}'
        handler = llms.LlmHandler(cache_root / condition)
        handler.prompt_records = []
        single_handlers[condition] = handler
        output, metrics = _timed_handler_call(
            handler,
            lambda handler=handler, model=model: get_llm_general_extraction_json(
                handler,
                excerpt=trial['excerpt_text'],
                focus_question=trial['focus_question'],
                model=model,
            ),
        )
        observable['outputs'][condition] = output
        observable['condition_metrics'][condition] = _attach_metrics(metrics, model=model)

    observable['prompts'] = _collect_general_prompts_from_handlers(
        crowd_handler,
        single_handlers,
        layout=layout,
    )
    return observable


def _run_live_trial(
    trial: dict[str, Any],
    *,
    layout: dict[str, Any],
    consensus_model: str,
    cache_root: Path,
) -> dict[str, Any]:
    if trial['trial_pool'] == 'general':
        return _run_general_trial(
            trial,
            layout=layout,
            consensus_model=consensus_model,
            cache_root=cache_root,
        )
    return _run_biology_trial(
        trial,
        layout=layout,
        consensus_model=consensus_model,
        cache_root=cache_root,
    )


def _aggregate_rows(
    observables: list[dict[str, Any]],
    *,
    conditions: tuple[str, ...],
) -> list[dict[str, Any]]:
    rows = []
    trial_pools = sorted({observable['trial_pool'] for observable in observables})
    scopes = [('overall', None), *[(pool, pool) for pool in trial_pools]]

    for scope, pool in scopes:
        for condition in conditions:
            pool_observables = [
                observable for observable in observables
                if pool is None or observable['trial_pool'] == pool
            ]
            metrics = [
                observable['condition_metrics'][condition]
                for observable in pool_observables
            ]
            usage_values = [metric.get('usage') or {} for metric in metrics]
            model = next(
                (metric.get('model') for metric in metrics if metric.get('model')),
                None,
            )
            rows.append({
                'scope': scope,
                'trial_pool': pool or '',
                'condition': condition,
                'model': model,
                'n_trials': len(pool_observables),
                'mean_wall_time_sec': (
                    sum(metric.get('duration_sec') or 0.0 for metric in metrics) / len(metrics)
                    if metrics else 0.0
                ),
                'mean_llm_time_sec': (
                    sum(metric.get('llm_duration_sec') or 0.0 for metric in metrics) / len(metrics)
                    if metrics else 0.0
                ),
                'mean_calls': (
                    sum(usage.get('calls') or 0 for usage in usage_values) / len(usage_values)
                    if usage_values else 0.0
                ),
                'mean_known_total_tokens': (
                    sum(usage.get('known_total_tokens') or 0 for usage in usage_values)
                    / len(usage_values)
                    if usage_values else 0.0
                ),
            })
    return rows


def _trial_meta(trial: dict[str, Any], *, dry_run: bool) -> dict[str, Any]:
    meta: dict[str, Any] = {
        'record_type': 'trial_meta',
        'trial_id': trial['trial_id'],
        'fixture_trial_id': trial.get('fixture_trial_id', trial['trial_id']),
        'trial_pool': trial['trial_pool'],
        'profile_id': trial['profile_id'],
        'section': trial['section'],
        'dry_run': dry_run,
    }
    if trial.get('excerpt_preparation') is not None:
        meta['excerpt_preparation'] = trial['excerpt_preparation']
    if trial.get('source_excerpt_chars') is not None:
        meta['source_excerpt_chars'] = trial['source_excerpt_chars']
    if trial['trial_pool'] == 'biology':
        meta.update({
            'gene_id': trial['gene_id'],
            'gene_name': trial['gene_name'],
            'pmc_id': trial.get('pmc_id'),
        })
    else:
        meta.update({
            'category': trial['category'],
            'source_id': trial['source_id'],
            'focus_question': trial['focus_question'],
        })
    return meta


def run_bias_experiment(
    *,
    config_path: Path,
    n_trials: int | None = None,
    run_id: str | None = None,
    dry_run: bool = False,
    distribution=None,
    seed: int | None = None,
) -> Path:
    from autoannotation.section_excerpt_config import section_excerpt_config_from_env
    from autoannotation.worker_env import load_worker_env_into_process

    load_worker_env_into_process()
    config_path = Path(config_path)
    config = load_yaml_config(config_path)
    experiment_id = config.get('experiment_id')
    if experiment_id not in ALLOWED_EXPERIMENT_IDS:
        raise ValueError(
            f'expected experiment_id in {sorted(ALLOWED_EXPERIMENT_IDS)!r}, got {experiment_id!r}',
        )

    fixture_config = config.get('fixtures') or {}
    items, fixture_documents = load_experiment_items(
        fixture_config,
        fixture_path=_fixture_path,
    )
    distribution = parse_distribution(
        distribution if distribution is not None else config.get('distribution'),
    )
    if distribution is not None:
        requested_trials = sum(distribution.values())
    else:
        requested_trials = config.get('n_trials', 10) if n_trials is None else n_trials
    if n_trials is not None and n_trials != requested_trials:
        raise ValueError(
            f'--n-trials={n_trials} conflicts with distribution total {requested_trials}',
        )
    max_trials = config.get('max_trials', len(items))
    selection_seed = seed if seed is not None else config.get('selection_seed', 42)
    if distribution is not None:
        validate_distribution(
            items,
            distribution,
            fixture_config=fixture_config,
        )
    selected = select_trials(
        items,
        requested_trials,
        distribution=distribution,
        seed=selection_seed,
        max_trials=max_trials,
    )
    run_trials = expand_trials_for_excerpts(selected)

    model_config = config.get('models') or {}
    extractor_models = list(model_config.get('extractors') or ())
    layout = build_condition_layout(extractor_models)
    condition_models = dict(layout['condition_models'])
    consensus_model = model_config.get('consensus')
    if not consensus_model:
        raise ValueError('models.consensus is required')
    condition_models[CONSENSUS_CONDITION] = consensus_model
    layout = dict(layout)
    layout['condition_models'] = condition_models
    conditions = layout['conditions']

    trial_pools = sorted({trial['trial_pool'] for trial in run_trials})
    run_id = run_id or new_run_id()
    output_dir = PAPER_DIR / 'results' / experiment_id / run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    records_path = output_dir / 'records.jsonl'
    records_path.write_text('')

    cache_policy = {
        'requested': config.get('cache_policy', 'unspecified'),
        'actual': (
            'not_applicable_dry_run'
            if dry_run
            else 'run_local_isolated_caches_for_crowd_and_each_single_arm'
        ),
    }
    excerpt_cfg = section_excerpt_config_from_env()
    manifest: dict[str, Any] = {
        'experiment_id': experiment_id,
        'run_id': run_id,
        'dry_run': dry_run,
        'git_sha': _git_sha(),
        'config_path': str(config_path),
        'config_hash': stable_json_hash(config),
        'fixture_hash': stable_json_hash(fixture_documents),
        'fixture_hashes': {
            name: stable_json_hash(document)
            for name, document in fixture_documents.items()
        },
        'n_fixture_trials': len(selected),
        'n_run_trials': len(run_trials),
        'trial_pools': {
            pool: sum(trial['trial_pool'] == pool for trial in run_trials)
            for pool in trial_pools
        },
        'distribution': distribution,
        'selection_seed': selection_seed if distribution else None,
        'model_tags': {
            'extractors': extractor_models,
            'consensus': consensus_model,
        },
        'conditions': list(conditions),
        'condition_models': condition_models,
        'groundedness': {'enabled': False},
        'cache_policy': cache_policy,
        'section_excerpt_config': {
            'chunking_enabled': excerpt_cfg.chunking_enabled,
            'max_chars': excerpt_cfg.max_chars,
            'retrieval_threshold_chars': excerpt_cfg.retrieval_threshold_chars,
        },
        'timestamp': datetime.now(timezone.utc).isoformat(),
    }
    if 'biology' in trial_pools:
        manifest['extraction_fields'] = list(BIOLOGY_FIELDS)
    if 'general' in trial_pools:
        manifest['extraction_fields_by_pool'] = {
            'general': list(GENERAL_EXTRACTION_FIELDS),
        }
        manifest.setdefault('field_kinds_by_pool', {})['general'] = GENERAL_FIELD_KINDS
    if 'biology' in trial_pools and 'general' in trial_pools:
        manifest['extraction_fields_by_pool'] = {
            'biology': list(BIOLOGY_FIELDS),
            'general': list(GENERAL_EXTRACTION_FIELDS),
        }
        manifest['field_kinds_by_pool'] = {
            'biology': {
                'function': 'string',
                'functional_category': 'array',
                'drug_susc_impact': 'string',
                'infection_impact': 'string',
                'essential_in_vitro': 'boolean',
                'essential_in_vivo': 'boolean',
            },
            'general': GENERAL_FIELD_KINDS,
        }
    write_json(output_dir / 'manifest.json', manifest)

    for trial in run_trials:
        append_jsonl(records_path, _trial_meta(trial, dry_run=dry_run))

    observables = []
    if dry_run:
        for trial in run_trials:
            observable = _empty_observable(trial, conditions=conditions)
            observables.append(observable)
            append_jsonl(records_path, observable)
            write_json(output_dir / 'trials' / f"{trial['trial_id']}.json", observable)
        write_aggregate_csv(
            output_dir / 'aggregate.csv',
            _aggregate_rows(observables, conditions=conditions),
        )
        return output_dir

    for trial in run_trials:
        observable = _run_live_trial(
            trial,
            layout=layout,
            consensus_model=consensus_model,
            cache_root=output_dir / '_llm_cache' / trial['trial_id'],
        )
        observables.append(observable)
        append_jsonl(records_path, observable)
        write_json(output_dir / 'trials' / f"{trial['trial_id']}.json", observable)

    write_aggregate_csv(
        output_dir / 'aggregate.csv',
        _aggregate_rows(observables, conditions=conditions),
    )
    return output_dir


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Run the primary 1-vs-3 bias experiment.')
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--n-trials', type=int)
    parser.add_argument(
        '--distribution',
        action='append',
        default=[],
        help=(
            'Quota as profile:count (repeatable). Organisms: mtb-h37rv, ecoli-k12-mg1655, '
            'tcruzi-clbrener (aliases mtb, ecoli, tcruzi). General: truthful, grounded, trap.'
        ),
    )
    parser.add_argument(
        '--seed',
        type=int,
        help='Shuffle seed when using --distribution (default from config or 42).',
    )
    parser.add_argument('--run-id')
    parser.add_argument('--dry-run', action='store_true')
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    distribution = parse_distribution(args.distribution) if args.distribution else None
    output_dir = run_bias_experiment(
        config_path=args.config,
        n_trials=args.n_trials,
        run_id=args.run_id,
        dry_run=args.dry_run,
        distribution=distribution,
        seed=args.seed,
    )
    print(output_dir)


if __name__ == '__main__':
    main()
