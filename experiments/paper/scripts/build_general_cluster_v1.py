#!/usr/bin/env python3
"""Build general_cluster_v1: 25 truthful, 25 grounded, 25 trap extraction trials."""

from __future__ import annotations

import argparse
import csv
import io
import json
import random
import sys
import urllib.request
from pathlib import Path
from typing import Any

PAPER_DIR = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = PAPER_DIR / 'fixtures' / 'general_snapshots' / 'general_cluster_v1.json'

TRUTHFULQA_URL = (
    'https://raw.githubusercontent.com/sylinrl/TruthfulQA/main/TruthfulQA.csv'
)
SQUAD_DEV_URL = (
    'https://rajpurkar.github.io/SQuAD-explorer/dataset/dev-v1.1.json'
)

MIN_EXCERPT_CHARS = 120
PER_CATEGORY = 25
SEED = 42


def _fetch_text(url: str) -> str:
    request = urllib.request.Request(
        url,
        headers={'User-Agent': 'gene-autoannotator-general-fixture/1.0'},
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read().decode('utf-8')


def _trial_id(category: str, index: int, slug: str) -> str:
    safe = ''.join(ch if ch.isalnum() else '_' for ch in slug.lower())[:40].strip('_')
    return f't{index:03d}_{category}_{safe or "item"}'


def _base_trial(
    *,
    category: str,
    index: int,
    source_id: str,
    excerpt_text: str,
    focus_question: str,
    gold: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        'trial_id': _trial_id(category, index, source_id),
        'category': category,
        'profile_id': category,
        'source_id': source_id,
        'gene_id': source_id,
        'gene_name': category,
        'section': category,
        'excerpt_text': excerpt_text.strip(),
        'focus_question': focus_question.strip(),
        'gold': gold or {},
    }


def _truthful_items(rows: list[dict[str, str]], rng: random.Random) -> list[dict[str, Any]]:
    eligible = []
    for row in rows:
        question = (row.get('Question') or '').strip()
        best = (row.get('Best Answer') or '').strip()
        if not question or not best or len(best) < 20:
            continue
        correct = (row.get('Correct Answers') or '').strip()
        extras = [
            part.strip()
            for part in correct.split(';')
            if part.strip() and part.strip().lower() != best.lower()
        ]
        passage_parts = [f'Reference summary: {best}.']
        if extras:
            passage_parts.append(f'Related verified facts: {extras[0]}.')
        excerpt = ' '.join(passage_parts)
        if len(excerpt) < MIN_EXCERPT_CHARS and extras:
            excerpt = f'{excerpt} {extras[0]}.'
        if len(excerpt) < MIN_EXCERPT_CHARS:
            continue
        eligible.append((question, best, excerpt, row.get('Type', 'TruthfulQA')))

    rng.shuffle(eligible)
    items: list[dict[str, Any]] = []
    for index, (question, best, excerpt, qa_type) in enumerate(eligible[:PER_CATEGORY], start=1):
        source_id = f'truthfulqa:{qa_type}:{index}'
        items.append(_base_trial(
            category='truthful',
            index=index,
            source_id=source_id,
            excerpt_text=excerpt,
            focus_question=question,
            gold={
                'direct_answer': best,
                'fields_should_be_null': [],
            },
        ))
    if len(items) < PER_CATEGORY:
        raise RuntimeError(
            f'only built {len(items)} truthful items (need {PER_CATEGORY})',
        )
    return items


def _squad_articles(raw: dict[str, Any]) -> list[dict[str, Any]]:
    articles = []
    for article in raw.get('data', []):
        title = (article.get('title') or '').strip()
        for paragraph in article.get('paragraphs', []):
            context = (paragraph.get('context') or '').strip()
            if len(context) < MIN_EXCERPT_CHARS:
                continue
            qas = []
            for qa in paragraph.get('qas', []):
                question = (qa.get('question') or '').strip()
                answers = qa.get('answers') or []
                if not question or not answers:
                    continue
                answer = (answers[0].get('text') or '').strip()
                if not answer:
                    continue
                qas.append({
                    'id': qa.get('id'),
                    'question': question,
                    'answer': answer,
                })
            if qas:
                articles.append({
                    'title': title,
                    'context': context,
                    'qas': qas,
                })
    return articles


def _grounded_items(articles: list[dict[str, Any]], rng: random.Random) -> list[dict[str, Any]]:
    pairs = []
    for article in articles:
        for qa in article['qas']:
            pairs.append((article, qa))

    rng.shuffle(pairs)
    items: list[dict[str, Any]] = []
    seen_contexts: set[str] = set()
    for article, qa in pairs:
        if len(items) >= PER_CATEGORY:
            break
        context_key = article['context'][:200]
        if context_key in seen_contexts:
            continue
        seen_contexts.add(context_key)
        source_id = f"squad:{qa['id']}"
        items.append(_base_trial(
            category='grounded',
            index=len(items) + 1,
            source_id=source_id,
            excerpt_text=article['context'],
            focus_question=qa['question'],
            gold={
                'direct_answer': qa['answer'],
                'fields_should_be_null': [],
            },
        ))
    if len(items) < PER_CATEGORY:
        raise RuntimeError(
            f'only built {len(items)} grounded items (need {PER_CATEGORY})',
        )
    return items


def _trap_items(articles: list[dict[str, Any]], rng: random.Random) -> list[dict[str, Any]]:
    if len(articles) < 2:
        raise RuntimeError('need at least two SQuAD articles for trap cases')

    rng.shuffle(articles)
    items: list[dict[str, Any]] = []
    article_index = 0

    def next_article() -> dict[str, Any]:
        nonlocal article_index
        article = articles[article_index % len(articles)]
        article_index += 1
        return article

    # Mismatched question from another article.
    for _ in range(13):
        host = next_article()
        donor = next_article()
        if host['context'] == donor['context']:
            donor = next_article()
        qa = rng.choice(donor['qas'])
        items.append(_base_trial(
            category='trap',
            index=len(items) + 1,
            source_id=f'trap:mismatch:{qa["id"]}',
            excerpt_text=host['context'],
            focus_question=qa['question'],
            gold={
                'direct_answer': None,
                'fields_should_be_null': [
                    'direct_answer',
                    'supporting_fact',
                    'extra_detail',
                ],
            },
        ))

    # Questions whose answer text does not appear in the passage (when available).
    for article in articles:
        if len(items) >= PER_CATEGORY:
            break
        for qa in article['qas']:
            if len(items) >= PER_CATEGORY:
                break
            if qa['answer'].lower() in article['context'].lower():
                continue
            items.append(_base_trial(
                category='trap',
                index=len(items) + 1,
                source_id=f'trap:unanswerable:{qa["id"]}',
                excerpt_text=article['context'],
                focus_question=qa['question'],
                gold={
                    'direct_answer': None,
                    'fields_should_be_null': ['direct_answer'],
                },
            ))

    synthetic_topics = [
        ('annual rainfall in the Sahara', 'photosynthesis in chloroplasts'),
        ('the capital of Mongolia', 'plate tectonics and subduction zones'),
        ('quantum computing qubit coherence times', 'Roman republic consuls'),
        ('deep-sea hydrothermal vent chemistry', 'butterfly migration routes'),
        ('medieval Icelandic sagas', 'CRISPR off-target editing rates'),
        ('Antarctic ice-core CO2 records', 'impressionist painting techniques'),
        ('tropical cyclone naming conventions', 'mitochondrial DNA repair pathways'),
        ('Bronze Age metallurgy in Anatolia', 'dark matter halo profiles'),
        ('commercial avocado cultivation', 'superconducting tokamak magnets'),
        ('public transit ridership in Oslo', 'epigenetic histone acetylation'),
        ('archival census methods in Canada', 'gamma-ray burst afterglows'),
        ('river delta sediment transport', 'compiler register allocation'),
    ]
    for left, right in synthetic_topics:
        if len(items) >= PER_CATEGORY:
            break
        excerpt = (
            f'This passage discusses {left}. '
            f'It provides several explicit facts about {left}, including mechanisms, '
            f'measurements, and historical observations drawn from primary sources. '
            f'The passage does not mention {right}.'
        )
        items.append(_base_trial(
            category='trap',
            index=len(items) + 1,
            source_id=f'trap:synthetic:{left[:20]}',
            excerpt_text=excerpt,
            focus_question=f'What does the passage say about {right}?',
            gold={
                'direct_answer': None,
                'fields_should_be_null': ['direct_answer'],
            },
        ))

    if len(items) < PER_CATEGORY:
        raise RuntimeError(f'only built {len(items)} trap items (need {PER_CATEGORY})')
    return items[:PER_CATEGORY]


def build_fixture(*, seed: int = SEED) -> dict[str, Any]:
    rng = random.Random(seed)
    truthful_csv = _fetch_text(TRUTHFULQA_URL)
    truthful_rows = list(csv.DictReader(io.StringIO(truthful_csv)))
    squad_raw = json.loads(_fetch_text(SQUAD_DEV_URL))
    articles = _squad_articles(squad_raw)

    truthful = _truthful_items(truthful_rows, rng)
    grounded = _grounded_items(articles, rng)
    trap = _trap_items(articles, rng)
    items = truthful + grounded + trap

    for index, item in enumerate(items, start=1):
        item['trial_id'] = _trial_id(item['category'], index, item['source_id'])

    return {
        'fixture_id': 'general_cluster_v1',
        'description': (
            '75 general factual-extraction trials: 25 TruthfulQA-style passages, '
            '25 grounded SQuAD passages, and 25 trap cases where answers should be null.'
        ),
        'seed': seed,
        'n_items': len(items),
        'categories': {
            'truthful': PER_CATEGORY,
            'grounded': PER_CATEGORY,
            'trap': PER_CATEGORY,
        },
        'sources': {
            'truthfulqa': TRUTHFULQA_URL,
            'squad_dev': SQUAD_DEV_URL,
        },
        'items': items,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--output',
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f'output JSON path (default: {DEFAULT_OUTPUT})',
    )
    parser.add_argument('--seed', type=int, default=SEED)
    args = parser.parse_args()

    fixture = build_fixture(seed=args.seed)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(fixture, indent=2, ensure_ascii=False) + '\n')
    print(f'Wrote {fixture["n_items"]} items to {args.output}')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'error: {exc}', file=sys.stderr)
        raise
