#!/usr/bin/env python3
"""Build a worker-bench JSONL of T. brucei TREU927 genes with enough papers.

Default cut is paper_count >= 10 from the ranking CSV (total papers found
across locus + name queries). Does not enable ortholog fallback.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

PROFILE_ID = "tbrucei-treu927"
_REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = Path("deploy/batches/tbrucei-treu927-ge10-papers.jsonl")
_RANKING_CANDIDATES = (
    Path("/data/tbrucei_paper_ranking/tbrucei_paper_ranking.csv"),
    Path("/data/tbrucei_paper_ranking.csv"),
    _REPO_ROOT / "data" / "tbrucei_paper_ranking" / "tbrucei_paper_ranking.csv",
)


def default_ranking_path() -> Path:
    for candidate in _RANKING_CANDIDATES:
        if candidate.is_file():
            return candidate
    return _RANKING_CANDIDATES[0]


def ranking_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf8", newline="") as handle:
        return list(csv.DictReader(handle))


def select_genes(rows, *, min_papers: int, count_field: str) -> list[dict[str, str]]:
    selected = []
    for row in rows:
        raw = (row.get(count_field) or "").strip()
        try:
            count = int(float(raw)) if raw else 0
        except ValueError:
            count = 0
        if count < min_papers:
            continue
        locus = (row.get("locus") or "").strip()
        if not locus:
            continue
        name = (row.get("name") or "").strip()
        selected.append({"locus": locus, "name": name, "paper_count": count})
    selected.sort(key=lambda item: (-item["paper_count"], item["locus"]))
    return selected


def write_jsonl(path: Path, genes: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf8") as handle:
        for gene in genes:
            job = {
                "profile": PROFILE_ID,
                "locus": gene["locus"],
                "allow_online_name_lookup": True,
                "allow_ortholog_fallback": False,
            }
            if gene["name"]:
                job["name"] = gene["name"]
            handle.write(json.dumps(job, separators=(",", ":")) + "\n")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ranking", type=Path, default=default_ranking_path())
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--min-papers", type=int, default=10)
    parser.add_argument(
        "--count-field",
        default="paper_count",
        help="CSV column to threshold (default: paper_count = total papers found)",
    )
    args = parser.parse_args(argv)

    rows = ranking_rows(args.ranking)
    genes = select_genes(rows, min_papers=args.min_papers, count_field=args.count_field)
    write_jsonl(args.output, genes)
    print(
        f"Wrote {len(genes)} jobs "
        f"({args.count_field}>={args.min_papers}) to {args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
