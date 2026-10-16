#!/usr/bin/env python3
"""Sample the Phase 2 labeled set for the consensus-arms experiment.

    PYTHONPATH=. python experiments/paper/scripts/sample_consensus_arms_sections.py \
      --seed 42 --per-organism 40

Draws ``--per-organism`` sections per organism from ``bias_cluster_v2.json``, spreading the
draw across papers (every paper in an organism is used once before any is reused), splits the
sampled papers 50/50 into dev / test (paper-disjoint, stratified by organism), writes empty
gold stubs (``stubs.jsonl``), ``sample_manifest.json``, and ``double_label_ids.json``
(random 15% of trial_ids for a second blind labeling pass).
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_FIXTURE = REPO_ROOT / "experiments/paper/fixtures/paper_snapshots/bias_cluster_v2.json"
DEFAULT_OUT_DIR = REPO_ROOT / "experiments/paper/fixtures/gold/consensus_arms_v1"
ORGANISMS = ("ecoli-k12-mg1655", "mtb-h37rv", "tcruzi-clbrener")
DOUBLE_LABEL_FRACTION = 0.15

STUB_KEYS = ("trial_id", "gene_id", "gene_name", "profile_id", "pmc_id", "section", "excerpt_text")


def _rng(seed: int, *salt: str) -> random.Random:
    return random.Random(":".join([str(seed), *salt]))


def sample_sections(items: list[dict[str, Any]], per_organism: int, seed: int) -> list[dict[str, Any]]:
    """Pick ``per_organism`` items per organism, maximizing distinct pmc_ids (round-robin over papers)."""
    out: list[dict[str, Any]] = []
    for org in ORGANISMS:
        pool = sorted((i for i in items if i["profile_id"] == org), key=lambda r: r["trial_id"])
        if len(pool) < per_organism:
            raise ValueError(f"{org}: only {len(pool)} items, need {per_organism}")
        rng = _rng(seed, "sample", org)
        by_paper: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in pool:
            by_paper[row["pmc_id"]].append(row)
        for rows in by_paper.values():
            rng.shuffle(rows)
        papers = sorted(by_paper)
        picked: list[dict[str, Any]] = []
        while len(picked) < per_organism:
            rng.shuffle(papers)
            for pmc in papers:
                if by_paper[pmc] and len(picked) < per_organism:
                    picked.append(by_paper[pmc].pop())
            papers = [p for p in papers if by_paper[p]]
        out.extend(picked)
    return out


def split_papers(sampled: list[dict[str, Any]], seed: int) -> tuple[list[str], list[str]]:
    """Split sampled papers 50/50 into (dev, test); stratified by organism, never overlapping."""
    dev: set[str] = set()
    test: set[str] = set()
    for org in ORGANISMS:
        papers = sorted({r["pmc_id"] for r in sampled if r["profile_id"] == org} - dev - test)
        _rng(seed, "split", org).shuffle(papers)
        # give the odd paper to whichever side is currently smaller
        half = len(papers) // 2
        dev_n = half + (len(papers) % 2 if len(dev) <= len(test) else 0)
        dev.update(papers[:dev_n])
        test.update(papers[dev_n:])
    return sorted(dev), sorted(test)


def pick_double_label_ids(
    sampled: list[dict[str, Any]], fraction: float = DOUBLE_LABEL_FRACTION, seed: int = 42
) -> list[str]:
    ids = sorted(r["trial_id"] for r in sampled)
    k = round(len(ids) * fraction)
    return sorted(_rng(seed, "double").sample(ids, k))


def make_stub(item: dict[str, Any]) -> dict[str, Any]:
    stub = {k: item[k] for k in STUB_KEYS}
    stub["fields"] = {}
    stub["needs_human"] = False
    return stub


def _write_json(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--per-organism", type=int, default=40)
    ap.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    ap.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = ap.parse_args(argv)

    items = json.loads(args.fixture.read_text())["items"]
    sampled = sample_sections(items, args.per_organism, args.seed)
    dev, test = split_papers(sampled, args.seed)
    double_ids = pick_double_label_ids(sampled, DOUBLE_LABEL_FRACTION, args.seed)

    out = args.out_dir
    out.mkdir(parents=True, exist_ok=True)
    with (out / "stubs.jsonl").open("w") as fh:
        for row in sampled:
            fh.write(json.dumps(make_stub(row), ensure_ascii=False) + "\n")
    _write_json(out / "dev_papers.json", dev)
    _write_json(out / "test_papers.json", test)
    _write_json(out / "double_label_ids.json", double_ids)
    _write_json(
        out / "sample_manifest.json",
        {
            "fixture": str(args.fixture.relative_to(REPO_ROOT)) if args.fixture.is_relative_to(REPO_ROOT) else str(args.fixture),
            "seed": args.seed,
            "total": len(sampled),
            "per_organism": {o: sum(r["profile_id"] == o for r in sampled) for o in ORGANISMS},
            "n_papers": {"dev": len(dev), "test": len(test)},
            "double_label_fraction": DOUBLE_LABEL_FRACTION,
            "n_double_label": len(double_ids),
            "trial_ids": [r["trial_id"] for r in sampled],
        },
    )
    print(f"wrote {len(sampled)} stubs, {len(dev)} dev / {len(test)} test papers, "
          f"{len(double_ids)} double-label ids -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
