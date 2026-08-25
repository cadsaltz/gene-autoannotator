from __future__ import annotations

import argparse
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from experiments.paper.runners.common import (
    BIOLOGY_FIELDS,
    append_jsonl,
    load_paper_snapshot_fixture,
    load_yaml_config,
    new_run_id,
    select_trials,
    stable_json_hash,
    write_aggregate_csv,
    write_json,
)
from experiments.paper.runners.groundedness import make_hf_nli_fn, score_field_groundedness

PAPER_DIR = Path(__file__).resolve().parents[1]
CONDITIONS = (
    'extractor_A',
    'extractor_B',
    'extractor_C',
    'consensus_D',
    'single_A',
    'single_B',
    'single_C',
)


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


def _empty_observable(trial: dict[str, Any]) -> dict[str, Any]:
    return {
        'record_type': 'trial_observable',
        'trial_id': trial['trial_id'],
        'profile_id': trial['profile_id'],
        'gene_id': trial['gene_id'],
        'gene_name': trial['gene_name'],
        'pmc_id': trial.get('pmc_id'),
        'section': trial['section'],
        'excerpt_text': trial['excerpt_text'],
        'outputs': {condition: None for condition in CONDITIONS},
        'condition_metrics': {
            condition: {
                'duration_sec': None,
                'llm_duration_sec': None,
                'usage': None,
            }
            for condition in CONDITIONS
        },
    }


def _run_live_trial(
    trial: dict[str, Any],
    *,
    extractor_models: list[str],
    consensus_model: str,
    cache_root: Path,
) -> dict[str, Any]:
    from autoannotation import llms, organisms

    profile = organisms.resolve_profile(trial['profile_id'])
    observable = _empty_observable(trial)
    crowd_handler = llms.LlmHandler(cache_root / 'crowd')
    candidates = []

    for label, model in zip(('A', 'B', 'C'), extractor_models):
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
        observable['condition_metrics'][condition] = metrics

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
    observable['outputs']['consensus_D'] = consensus
    observable['condition_metrics']['consensus_D'] = metrics

    for label, model in zip(('A', 'B', 'C'), extractor_models):
        condition = f'single_{label}'
        handler = llms.LlmHandler(cache_root / condition)
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
        observable['condition_metrics'][condition] = metrics

    return observable


def _field_score_records(
    observable: dict[str, Any],
    nli_fn: Callable[[str, str], dict[str, Any]],
) -> list[dict[str, Any]]:
    records = []
    for condition in CONDITIONS:
        output = observable['outputs'][condition]
        metrics = observable['condition_metrics'][condition]
        for field in BIOLOGY_FIELDS:
            value = output.get(field)
            score = score_field_groundedness(
                observable['excerpt_text'], field, value, nli_fn,
            )
            records.append({
                'record_type': 'field_score',
                'trial_id': observable['trial_id'],
                'condition': condition,
                'field': field,
                'value': value,
                **score,
                'duration_sec': metrics['duration_sec'],
                'calls': metrics['usage']['calls'],
                'cache_hits': metrics['usage']['cache_hits'],
                'known_total_tokens': metrics['usage']['known_total_tokens'],
                'token_usage_complete': metrics['usage']['token_usage_complete'],
            })
    return records


def _aggregate_rows(
    score_records: list[dict[str, Any]],
    observables: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows = []
    for condition in CONDITIONS:
        condition_scores = [
            record for record in score_records if record['condition'] == condition
        ]
        count = len(condition_scores)
        non_null_count = sum(
            record['groundedness_label'] != 'null' for record in condition_scores
        )
        metrics = [
            observable['condition_metrics'][condition] for observable in observables
        ]

        def rate(label: str) -> float:
            denominator = count if label == 'null' else non_null_count
            if not denominator:
                return 0.0
            return sum(
                record['groundedness_label'] == label for record in condition_scores
            ) / denominator

        rows.append({
            'condition': condition,
            'field_scores': count,
            'supported_rate': rate('supported'),
            'unsupported_rate': rate('unsupported'),
            'null_rate': rate('null'),
            'mean_wall_time_sec': (
                sum(metric['duration_sec'] for metric in metrics) / len(metrics)
                if metrics else 0.0
            ),
            'mean_calls': (
                sum(metric['usage']['calls'] for metric in metrics) / len(metrics)
                if metrics else 0.0
            ),
            'mean_known_total_tokens': (
                sum(metric['usage']['known_total_tokens'] for metric in metrics)
                / len(metrics)
                if metrics else 0.0
            ),
        })
    return rows


def _trial_json_path(output_dir: Path, trial_id: str) -> Path:
    return output_dir / 'trials' / f'{trial_id}.json'


def _load_completed_observable(output_dir: Path, trial_id: str) -> dict[str, Any] | None:
    path = _trial_json_path(output_dir, trial_id)
    if not path.is_file():
        return None
    data = json.loads(path.read_text())
    outputs = data.get('outputs') or {}
    # Require crowd extractors + consensus to treat the LLM stage as done.
    required = ('extractor_A', 'extractor_B', 'extractor_C', 'consensus_D')
    if any(outputs.get(key) is None for key in required):
        return None
    return data


def run_bias_experiment(
    *,
    config_path: Path,
    n_trials: int | None = None,
    run_id: str | None = None,
    dry_run: bool = False,
    resume: bool = False,
) -> Path:
    config_path = Path(config_path)
    config = load_yaml_config(config_path)
    experiment_id = config.get('experiment_id')
    if experiment_id != 'bias-1-vs-3-small':
        raise ValueError(f'expected experiment_id bias-1-vs-3-small, got {experiment_id!r}')

    fixture_config = config.get('fixtures') or {}
    paper_fixture_path = _fixture_path(fixture_config['papers'])
    paper_fixture = json.loads(paper_fixture_path.read_text())
    items = load_paper_snapshot_fixture(paper_fixture_path)
    requested_trials = config.get('n_trials', 10) if n_trials is None else n_trials
    selected = select_trials(items, requested_trials)

    fixture_documents = {'papers': paper_fixture}
    if fixture_config.get('genes'):
        genes_path = _fixture_path(fixture_config['genes'])
        fixture_documents['genes'] = json.loads(genes_path.read_text())

    model_config = config.get('models') or {}
    extractor_models = list(model_config.get('extractors') or ())
    if len(extractor_models) != 3:
        raise ValueError('models.extractors must contain exactly three model tags')
    consensus_model = model_config.get('consensus')
    if not consensus_model:
        raise ValueError('models.consensus is required')

    run_id = run_id or new_run_id()
    output_dir = PAPER_DIR / 'results' / experiment_id / run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    records_path = output_dir / 'records.jsonl'
    if not resume:
        records_path.write_text('')

    cache_policy = {
        'requested': config.get('cache_policy', 'unspecified'),
        'actual': (
            'not_applicable_dry_run'
            if dry_run
            else 'run_local_isolated_caches_for_crowd_and_each_single_arm'
        ),
    }
    manifest = {
        'experiment_id': experiment_id,
        'run_id': run_id,
        'dry_run': dry_run,
        'resume': resume,
        'git_sha': _git_sha(),
        'config_path': str(config_path),
        'config_hash': stable_json_hash(config),
        'fixture_hash': stable_json_hash(fixture_documents),
        'fixture_hashes': {
            name: stable_json_hash(document)
            for name, document in fixture_documents.items()
        },
        'n_trials': len(selected),
        'model_tags': {
            'extractors': extractor_models,
            'consensus': consensus_model,
        },
        'nli_model_id': (config.get('nli') or {}).get('model_id', 'roberta-large-mnli'),
        'cache_policy': cache_policy,
        'timestamp': datetime.now(timezone.utc).isoformat(),
    }
    write_json(output_dir / 'manifest.json', manifest)

    # Always rebuild records.jsonl at the end for a consistent artifact.
    rebuilt_records: list[dict[str, Any]] = []
    for trial in selected:
        rebuilt_records.append({
            'record_type': 'trial_meta',
            'trial_id': trial['trial_id'],
            'profile_id': trial['profile_id'],
            'gene_id': trial['gene_id'],
            'gene_name': trial['gene_name'],
            'pmc_id': trial.get('pmc_id'),
            'section': trial['section'],
            'dry_run': dry_run,
        })

    observables = []
    if dry_run:
        for trial in selected:
            observable = _empty_observable(trial)
            observables.append(observable)
            rebuilt_records.append(observable)
            write_json(_trial_json_path(output_dir, trial['trial_id']), observable)
        records_path.write_text('')
        for record in rebuilt_records:
            append_jsonl(records_path, record)
        write_aggregate_csv(
            output_dir / 'aggregate.csv',
            _aggregate_rows([], []),
        )
        return output_dir

    score_records = []
    nli_fn = make_hf_nli_fn(manifest['nli_model_id'])
    for trial in selected:
        trial_id = trial['trial_id']
        observable = None
        if resume:
            observable = _load_completed_observable(output_dir, trial_id)
            if observable is not None:
                print(f'resume: skipping LLM for completed trial {trial_id}', flush=True)
        if observable is None:
            observable = _run_live_trial(
                trial,
                extractor_models=extractor_models,
                consensus_model=consensus_model,
                cache_root=output_dir / '_llm_cache' / trial_id,
            )
            write_json(_trial_json_path(output_dir, trial_id), observable)
        observables.append(observable)
        rebuilt_records.append(observable)
        trial_scores = _field_score_records(observable, nli_fn)
        score_records.extend(trial_scores)
        rebuilt_records.extend(trial_scores)

    records_path.write_text('')
    for record in rebuilt_records:
        append_jsonl(records_path, record)

    write_aggregate_csv(
        output_dir / 'aggregate.csv',
        _aggregate_rows(score_records, observables),
    )
    return output_dir


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Run the primary 1-vs-3 bias experiment.')
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--n-trials', type=int)
    parser.add_argument('--run-id')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument(
        '--resume',
        action='store_true',
        help='Skip trials that already have complete trials/<id>.json outputs; re-score NLI.',
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    output_dir = run_bias_experiment(
        config_path=args.config,
        n_trials=args.n_trials,
        run_id=args.run_id,
        dry_run=args.dry_run,
        resume=args.resume,
    )
    print(output_dir)


if __name__ == '__main__':
    main()
