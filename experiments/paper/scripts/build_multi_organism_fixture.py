#!/usr/bin/env python3
"""Build a frozen multi-organism paper snapshot fixture from PMC cache.

Collection strategy (same intent as bias_cluster_v1):
- gene-linked PMC sections with non-empty cached text
- section mentions gene locus or name
- target-organism patterns present, no excluded off-target species
- spread sections across papers where possible; balanced section mix
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
import urllib.request
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from autoannotation import organisms, pmc

PROFILE_ALIASES = {
    'mtb': 'mtb-h37rv',
    'ecoli': 'ecoli-k12-mg1655',
    'e-coli': 'ecoli-k12-mg1655',
    'tcruzi': 'tcruzi-clbrener',
    't-cruzi': 'tcruzi-clbrener',
}

SECTION_TYPES = ('abstract', 'results', 'discussion')
MIN_EXCERPT_CHARS = 200

LOCUS_PATTERNS = {
    'mtb-h37rv': re.compile(r'\b(Rv\d{4}[Ac]?)\b'),
    'ecoli-k12-mg1655': re.compile(r'\b(b\d{4})\b'),
    'tcruzi-clbrener': re.compile(r'\b(TcCLB\.\d+\.\d+)\b'),
}


@dataclass(frozen=True)
class GeneRecord:
    profile_id: str
    gene_id: str
    gene_name: str


@dataclass(frozen=True)
class SectionRecord:
    pmc_id: str
    section: str
    text: str


def _resolve_profile_id(value: str) -> str:
    return PROFILE_ALIASES.get(value.strip().lower(), value.strip())


def _load_mtb_genes(table_path: Path) -> list[GeneRecord]:
    table = pd.read_csv(table_path, sep='\t')
    cds = table.loc[table['Feature'].eq('CDS')].copy()
    genes: list[GeneRecord] = []
    for locus, row in cds.set_index('Locus').iterrows():
        locus = str(locus).strip()
        if not locus or locus == 'nan':
            continue
        name = str(row.get('Name') or locus).strip()
        genes.append(GeneRecord('mtb-h37rv', locus, name))
    return genes


def _organism_hits(text: str, profile) -> tuple[bool, bool, bool]:
    target = any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in profile.target_patterns)
    off_target = any(
        re.search(pattern, text, flags=re.IGNORECASE)
        for pattern in (profile.off_target_patterns or ())
    )
    excluded = any(
        re.search(pattern, text, flags=re.IGNORECASE)
        for pattern in (profile.excluded_species_patterns or ())
    )
    return target, off_target, excluded


def _fetch_kegg_genes_cached(
    org_code: str,
    *,
    locus_pattern: re.Pattern[str],
    cache_path: Path,
) -> list[GeneRecord]:
    if cache_path.is_file():
        payload = json.loads(cache_path.read_text(encoding='utf-8'))
        return [
            GeneRecord(item['profile_id'], item['gene_id'], item['gene_name'])
            for item in payload
        ]
    genes = _fetch_kegg_genes(org_code, locus_pattern=locus_pattern)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps([
        {
            'profile_id': gene.profile_id,
            'gene_id': gene.gene_id,
            'gene_name': gene.gene_name,
        }
        for gene in genes
    ], indent=2) + '\n')
    return genes


def _fetch_kegg_genes(org_code: str, *, locus_pattern: re.Pattern[str]) -> list[GeneRecord]:
    url = f'https://rest.kegg.jp/list/{org_code}'
    with urllib.request.urlopen(url, timeout=120) as response:
        body = response.read().decode('utf-8')
    profile_id = {'eco': 'ecoli-k12-mg1655'}[org_code]
    genes: list[GeneRecord] = []
    for line in body.splitlines():
        if not line.strip():
            continue
        entry, description = line.split('\t', 1)
        prefix, locus = entry.split(':', 1)
        if prefix != org_code or not locus_pattern.fullmatch(locus):
            continue
        name = description.split(',', 1)[0].strip() or locus
        genes.append(GeneRecord(profile_id, locus, name))
    return genes


def _discover_tcruzi_genes_from_cache(cache_dir: Path, *, limit: int = 8000) -> list[GeneRecord]:
    pattern = LOCUS_PATTERNS['tcruzi-clbrener']
    counts: Counter[str] = Counter()
    for subdir in SECTION_TYPES:
        section_dir = cache_dir / subdir
        if not section_dir.is_dir():
            continue
        for path in section_dir.glob('*.txt'):
            try:
                counts.update(pattern.findall(path.read_text(encoding='utf-8', errors='ignore')))
            except OSError:
                continue
    return [
        GeneRecord('tcruzi-clbrener', locus, locus)
        for locus, _ in counts.most_common(limit)
    ]


def _load_genes_for_profile(
    profile_id: str,
    *,
    repo_root: Path,
    cache_dir: Path,
) -> dict[str, GeneRecord]:
    profile_id = _resolve_profile_id(profile_id)
    if profile_id == 'mtb-h37rv':
        table_path = repo_root / 'Mycobacterium_tuberculosis_H37Rv_txt_v5.txt'
        records = _load_mtb_genes(table_path)
    elif profile_id == 'ecoli-k12-mg1655':
        cache_path = repo_root / 'experiments/paper/fixtures/gene_sets/ecoli_k12_mg1655_kegg_genes.json'
        records = _fetch_kegg_genes_cached(
            'eco',
            locus_pattern=re.compile(r'^b\d{4}$'),
            cache_path=cache_path,
        )
    elif profile_id == 'tcruzi-clbrener':
        records = _discover_tcruzi_genes_from_cache(cache_dir)
    else:
        raise ValueError(f'unsupported profile_id for gene loading: {profile_id}')
    return {record.gene_id: record for record in records}


def _load_gen_json_pmc_map(repo_root: Path) -> dict[tuple[str, str], set[str]]:
    mapping: dict[tuple[str, str], set[str]] = defaultdict(set)
    for path in repo_root.glob('gen_json/**/*.json'):
        try:
            payload = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError):
            continue
        profile_id = payload.get('annotation_metadata', {}).get('profile_id')
        gene_id = payload.get('gene_id')
        if not profile_id or not gene_id:
            continue
        literature = payload.get('annotation_metadata', {}).get('literature') or {}
        for key in ('pmc_ids_selected', 'pmc_ids_analyzed', 'pmc_ids_retrieved'):
            for pmc_id in literature.get(key) or ():
                mapping[(profile_id, gene_id)].add(str(pmc_id))
    return mapping


def _iter_cached_sections(cache_dir: Path) -> list[SectionRecord]:
    sections: list[SectionRecord] = []
    for section in SECTION_TYPES:
        section_dir = cache_dir / section
        if not section_dir.is_dir():
            continue
        for path in section_dir.glob('*.txt'):
            pmc_id = path.stem
            if pmc_id.startswith('PMC'):
                pmc_id = pmc_id[3:]
            for suffix in ('_abstract', '_results', '_discussion'):
                if pmc_id.endswith(suffix):
                    pmc_id = pmc_id[: -len(suffix)]
                    break
            try:
                text = path.read_text(encoding='utf-8', errors='ignore').strip()
            except OSError:
                continue
            if len(text) < MIN_EXCERPT_CHARS:
                continue
            sections.append(SectionRecord(pmc_id=pmc_id, section=section, text=text))
    return sections


def _section_has_gene_hit(text: str, gene_id: str, gene_name: str) -> bool:
    lowered = text.lower()
    if gene_id and re.search(rf'\b{re.escape(gene_id)}\b', text, flags=re.IGNORECASE):
        return True
    if (
        gene_name
        and gene_name.lower() not in {gene_id.lower() if gene_id else ''}
        and gene_name.lower() in lowered
    ):
        return True
    return False


def _section_passes_organism_filter(text: str, profile_id: str, profile) -> bool:
    target_hit, off_target_hit, excluded_hit = _organism_hits(text, profile)
    if excluded_hit or off_target_hit:
        return False
    if target_hit:
        return True
    # T. cruzi sections often mention TcCLB loci without repeating the species name.
    if profile_id == 'tcruzi-clbrener':
        return True
    return False


def _collect_candidates_for_profile(
    profile_id: str,
    genes_by_id: dict[str, GeneRecord],
    sections: list[SectionRecord],
    gen_json_pmcs: dict[tuple[str, str], set[str]],
) -> list[dict]:
    profile = organisms.resolve_profile(profile_id)
    locus_pattern = LOCUS_PATTERNS[profile_id]
    candidates: list[dict] = []

    for section in sections:
        loci = set(locus_pattern.findall(section.text))
        if not loci:
            continue
        target_hit, off_target_hit, excluded_hit = _organism_hits(section.text, profile)
        if excluded_hit or off_target_hit:
            continue
        if not _section_passes_organism_filter(section.text, profile_id, profile):
            continue
        for locus in loci:
            gene = genes_by_id.get(locus)
            if gene is None:
                continue
            if not _section_has_gene_hit(section.text, gene.gene_id, gene.gene_name):
                continue
            bonus = 1.0 if section.pmc_id in gen_json_pmcs.get((profile_id, gene.gene_id), set()) else 0.0
            candidates.append({
                'profile_id': profile_id,
                'gene_id': gene.gene_id,
                'gene_name': gene.gene_name,
                'locus': gene.gene_id,
                'pmc_id': section.pmc_id,
                'section': section.section,
                'excerpt_text': section.text,
                '_score': bonus + (0.3 if section.section == 'results' else 0.1),
            })
    return candidates


def _balanced_section_targets(total: int) -> dict[str, int]:
    base = total // len(SECTION_TYPES)
    remainder = total % len(SECTION_TYPES)
    targets = {section: base for section in SECTION_TYPES}
    for section in SECTION_TYPES[:remainder]:
        targets[section] += 1
    return targets


def _select_items(
    pool: list[dict],
    *,
    target_count: int,
    rng: random.Random,
    max_sections_per_paper: int,
) -> list[dict]:
    if not pool:
        return []

    by_section: dict[str, list[dict]] = defaultdict(list)
    for item in pool:
        by_section[item['section']].append(item)
    for section_items in by_section.values():
        section_items.sort(key=lambda item: item.get('_score', 0.0), reverse=True)
        rng.shuffle(section_items)

    selected: list[dict] = []
    paper_counts: Counter[str] = Counter()
    section_targets = _balanced_section_targets(target_count)

    def _paper_key(item: dict) -> str:
        return f"{item['profile_id']}:{item['pmc_id']}"

    def _take(item: dict) -> None:
        selected.append(item)
        paper_counts[_paper_key(item)] += 1

    for section, quota in section_targets.items():
        taken = 0
        for item in by_section.get(section, []):
            if taken >= quota:
                break
            if item in selected:
                continue
            if paper_counts[_paper_key(item)] >= max_sections_per_paper:
                continue
            _take(item)
            taken += 1

    remaining = [item for item in pool if item not in selected]
    remaining.sort(key=lambda item: item.get('_score', 0.0), reverse=True)
    rng.shuffle(remaining)
    for item in remaining:
        if len(selected) >= target_count:
            break
        if paper_counts[_paper_key(item)] >= max_sections_per_paper:
            continue
        _take(item)

    for item in remaining:
        if len(selected) >= target_count:
            break
        if item in selected:
            continue
        _take(item)

    selected = selected[:target_count]
    selected.sort(key=lambda item: (item['profile_id'], item['gene_id'], item['pmc_id'], item['section']))
    for index, item in enumerate(selected, start=1):
        item['trial_id'] = (
            f"t{index:03d}_{item['gene_id']}_PMC{item['pmc_id']}_{item['section']}"
        )
        item.pop('_score', None)
    return selected


def _expand_cache_for_genes(
    paper_manager: pmc.PmcPaperManager,
    genes: list[GeneRecord],
    *,
    max_genes: int,
    max_papers_per_gene: int,
) -> None:
    for gene in genes[:max_genes]:
        profile = organisms.resolve_profile(gene.profile_id)
        paper_manager.organism_profile = profile
        try:
            ranked = paper_manager.get_ranked_papers(gene.gene_id, gene.gene_name)
        except Exception as exc:
            print(f'WARN expand skip {gene.gene_id}: {exc}', flush=True)
            continue
        selected, _ = paper_manager.select_papers_to_analyze(
            ranked,
            gene.gene_id,
            gene.gene_name,
            max_papers=max_papers_per_gene,
        )
        for pmc_id in selected:
            try:
                paper_manager.get_abstract(pmc_id)
                paper_manager.get_results(pmc_id)
                paper_manager.get_discussion(pmc_id)
            except Exception:
                continue


def build_fixture(
    *,
    per_organism: dict[str, int],
    cache_dir: Path,
    repo_root: Path,
    seed: int,
    max_sections_per_paper: int,
    expand_cache: bool = False,
) -> dict:
    rng = random.Random(seed)
    paper_manager = pmc.PmcPaperManager(str(cache_dir))
    gen_json_pmcs = _load_gen_json_pmc_map(repo_root)
    all_items: list[dict] = []

    for profile_id, target_count in per_organism.items():
        profile_id = _resolve_profile_id(profile_id)
        genes_by_id = _load_genes_for_profile(profile_id, repo_root=repo_root, cache_dir=cache_dir)
        genes = list(genes_by_id.values())
        rng.shuffle(genes)

        sections = _iter_cached_sections(cache_dir)
        pool = _collect_candidates_for_profile(
            profile_id,
            genes_by_id,
            sections,
            gen_json_pmcs,
        )
        if expand_cache and len(pool) < target_count:
            print(
                f'Expanding PMC cache for {profile_id}: pool={len(pool)} target={target_count}',
                flush=True,
            )
            _expand_cache_for_genes(
                paper_manager,
                genes,
                max_genes=min(250, max(50, target_count - len(pool))),
                max_papers_per_gene=5,
            )
            sections = _iter_cached_sections(cache_dir)
            pool = _collect_candidates_for_profile(
                profile_id,
                genes_by_id,
                sections,
                gen_json_pmcs,
            )
        selected = _select_items(
            pool,
            target_count=target_count,
            rng=rng,
            max_sections_per_paper=max_sections_per_paper,
        )
        if len(selected) < target_count:
            if expand_cache:
                raise RuntimeError(
                    f'only collected {len(selected)}/{target_count} sections for {profile_id} '
                    f'after cache expansion (pool={len(pool)})'
                )
            raise RuntimeError(
                f'only collected {len(selected)}/{target_count} sections for {profile_id} '
                f'(pool={len(pool)}). Re-run with --expand-cache to fetch more PMC papers.'
            )
        all_items.extend(selected)

    all_items.sort(key=lambda item: item['trial_id'])
    profile_summary = Counter(item['profile_id'] for item in all_items)
    section_summary = Counter(item['section'] for item in all_items)
    paper_summary = Counter(item['pmc_id'] for item in all_items)
    gene_summary = Counter((item['profile_id'], item['gene_id']) for item in all_items)

    return {
        'fixture_id': 'paper_snapshots/bias_cluster_v2',
        'selection_criteria': (
            'Multi-organism gene-linked PMC sections scanned from cached abstract/results/discussion '
            'text with organism target patterns, no excluded off-target species, and explicit gene '
            'locus/name mention. Spread across papers where possible; balanced section mix per organism.'
        ),
        'build_metadata': {
            'seed': seed,
            'per_organism': {_resolve_profile_id(k): v for k, v in per_organism.items()},
            'max_sections_per_paper': max_sections_per_paper,
            'cached_sections_scanned': len(sections),
            'profile_counts': dict(profile_summary),
            'section_counts': dict(section_summary),
            'unique_papers': len(paper_summary),
            'unique_genes': len(gene_summary),
        },
        'items': all_items,
    }


def _parse_per_organism(values: list[str]) -> dict[str, int]:
    parsed: dict[str, int] = {}
    for raw in values:
        if ':' not in raw:
            raise ValueError(f'expected PROFILE:COUNT, got {raw!r}')
        profile, count_text = raw.split(':', 1)
        parsed[_resolve_profile_id(profile.strip())] = int(count_text.strip())
    return parsed


def main() -> None:
    parser = argparse.ArgumentParser(description='Build multi-organism paper snapshot fixture.')
    parser.add_argument(
        '--per-organism',
        action='append',
        default=[],
        help='Organism quota as profile_id:count (repeatable). Example: mtb-h37rv:100',
    )
    parser.add_argument(
        '--output',
        type=Path,
        default=REPO_ROOT / 'experiments/paper/fixtures/paper_snapshots/bias_cluster_v2.json',
    )
    parser.add_argument('--cache-dir', type=Path, default=REPO_ROOT / '.cache')
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--max-sections-per-paper', type=int, default=2)
    parser.add_argument(
        '--expand-cache',
        action='store_true',
        help='Fetch additional PMC papers into cache when an organism pool is too small.',
    )
    args = parser.parse_args()

    per_organism = _parse_per_organism(args.per_organism)
    if not per_organism:
        per_organism = {
            'mtb-h37rv': 100,
            'ecoli-k12-mg1655': 100,
            'tcruzi-clbrener': 100,
        }

    fixture = build_fixture(
        per_organism=per_organism,
        cache_dir=args.cache_dir,
        repo_root=REPO_ROOT,
        seed=args.seed,
        max_sections_per_paper=args.max_sections_per_paper,
        expand_cache=args.expand_cache,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(fixture, indent=2, ensure_ascii=False) + '\n')

    gene_rows = sorted(
        {
            (item['profile_id'], item['gene_id'], item['gene_name'], item.get('locus', item['gene_id']))
            for item in fixture['items']
        },
        key=lambda row: (row[0], row[1]),
    )
    gene_set = {
        'fixture_id': 'gene_sets/bias_cluster_v2',
        'selection_criteria': 'Distinct genes referenced by bias_cluster_v2 paper snapshot items.',
        'items': [
            {
                'profile_id': profile_id,
                'gene_id': gene_id,
                'gene_name': gene_name,
                'locus': locus,
            }
            for profile_id, gene_id, gene_name, locus in gene_rows
        ],
    }
    gene_output = args.output.parent.parent / 'gene_sets' / 'bias_cluster_v2.json'
    gene_output.parent.mkdir(parents=True, exist_ok=True)
    gene_output.write_text(json.dumps(gene_set, indent=2, ensure_ascii=False) + '\n')

    meta = fixture['build_metadata']
    print(
        f"Wrote {len(fixture['items'])} trials to {args.output} "
        f"(profiles={meta['profile_counts']}, sections={meta['section_counts']}, "
        f"papers={meta['unique_papers']}, genes={meta['unique_genes']})"
    )


if __name__ == '__main__':
    main()
