import argparse
from collections import Counter
import json
import pandas as pd
from autoannotation.pmc import (
    PmcPaperManager,
    DEFAULT_MAX_PAPERS,
    DEFAULT_MAX_RANK,
    DEFAULT_MIN_PAPERS,
    DEFAULT_MIN_SCORE,
    DEFAULT_TARGET_RELEVANCE,
)


def load_myco_df():
    df = pd.read_csv(
        "./Mycobacterium_tuberculosis_H37Rv_txt_v5.txt",
        sep="\t"
    )

    df = (
        df.loc[df["Feature"].eq("CDS"), :]
        .set_index("Locus", drop=True)
        .sort_index()
    )

    return df

def summarize_ranked_records(records):
    scores = [record.score for record in records]
    retrieval_sources = Counter(
        source
        for record in records
        for source in record.retrieval_sources
    )
    warnings = Counter(
        warning
        for record in records
        for warning in record.warnings
    )

    if not scores:
        score_summary = {
            "min": 0.0,
            "max": 0.0,
            "mean": 0.0,
            "median": 0.0,
            "above_0_75": 0,
            "above_0_50": 0,
            "above_0_25": 0,
            "below_0_10": 0,
        }
    else:
        sorted_scores = sorted(scores)
        middle = len(sorted_scores) // 2
        if len(sorted_scores) % 2 == 0:
            median = (sorted_scores[middle - 1] + sorted_scores[middle]) / 2
        else:
            median = sorted_scores[middle]

        score_summary = {
            "min": round(min(scores), 3),
            "max": round(max(scores), 3),
            "mean": round(sum(scores) / len(scores), 3),
            "median": round(median, 3),
            "above_0_75": sum(score >= 0.75 for score in scores),
            "above_0_50": sum(score >= 0.50 for score in scores),
            "above_0_25": sum(score >= 0.25 for score in scores),
            "below_0_10": sum(score < 0.10 for score in scores),
        }

    return {
        "total": len(records),
        "retrieval_sources": dict(retrieval_sources),
        "warnings": dict(warnings),
        "score": score_summary,
    }

def relevance_record_to_dict(record):
    return {
        "pmc_id": record.pmc_id,
        "pmid": record.pmid,
        "score": record.score,
        "retrieval_sources": record.retrieval_sources,
        "title": record.title,
        "year": record.year,
        "section_hits": record.section_hits,
        "evidence_flags": record.evidence_flags,
        "score_components": record.score_components,
        "warnings": record.warnings,
    }

def format_record(record):
    sources = ",".join(record.retrieval_sources) or "unknown"
    warnings = ",".join(record.warnings) or "none"
    top_components = sorted(
        record.score_components.items(),
        key=lambda item: abs(item[1]),
        reverse=True,
    )[:5]
    components = ", ".join(f"{key}={value:+.3f}" for key, value in top_components)

    return "\n".join([
        f"PMC{record.pmc_id} | PMID {record.pmid or 'unknown'} | score {record.score:.3f}",
        f"  year: {record.year or 'unknown'} | sources: {sources} | warnings: {warnings}",
        f"  title: {record.title or '[missing title]'}",
        f"  top components: {components or 'none'}",
    ])

def print_summary(summary):
    print(f"Count: {summary['total']}")
    print("Retrieval sources:")
    for source, count in sorted(summary["retrieval_sources"].items()):
        print(f"  {source}: {count}")

    score = summary["score"]
    print("Score distribution:")
    print(f"  min/max: {score['min']:.3f}/{score['max']:.3f}")
    print(f"  mean/median: {score['mean']:.3f}/{score['median']:.3f}")
    print(f"  >=0.75: {score['above_0_75']}")
    print(f"  >=0.50: {score['above_0_50']}")
    print(f"  >=0.25: {score['above_0_25']}")
    print(f"  <0.10: {score['below_0_10']}")

    if summary["warnings"]:
        print("Warnings:")
        for warning, count in sorted(summary["warnings"].items()):
            print(f"  {warning}: {count}")

def main():
    parser = argparse.ArgumentParser(
        description="Fetch PMC IDs for a gene locus"
    )
    parser.add_argument("gene", help="Gene locus (e.g. Rv0001)")
    parser.add_argument("--cache", default="./.cache")
    parser.add_argument("--top", type=int, default=10, help="Number of top ranked papers to print")
    parser.add_argument("--bottom", type=int, default=5, help="Number of bottom ranked papers to print")
    parser.add_argument("--target-relevance", type=float, default=DEFAULT_TARGET_RELEVANCE)
    parser.add_argument("--min-score", type=float, default=DEFAULT_MIN_SCORE)
    parser.add_argument("--min-papers", type=int, default=DEFAULT_MIN_PAPERS)
    parser.add_argument("--max-papers", type=int, default=DEFAULT_MAX_PAPERS)
    parser.add_argument("--max-rank", type=int, default=DEFAULT_MAX_RANK)
    parser.add_argument("--json-out", help="Optional path for full ranked relevance JSON")

    args = parser.parse_args()

    # load annotation table
    mycobrowser_df = load_myco_df()

    if args.gene not in mycobrowser_df.index:
        raise KeyError(f"Gene not found: {args.gene}")

    name = mycobrowser_df.at[args.gene, "Name"]

    manager = PmcPaperManager(args.cache)
    ranked_records = manager.get_ranked_papers(args.gene, name)
    summary = summarize_ranked_records(ranked_records)
    selection = manager.select_relevance_records(
        ranked_records,
        target_relevance=args.target_relevance,
        min_score=args.min_score,
        max_rank=args.max_rank,
        min_papers=args.min_papers,
        max_papers=args.max_papers,
    )
    selected = selection.selected_records
    cumulative = selection.cumulative_relevance

    print(f"\n\nGene: {args.gene}")
    print(f"Name: {name}")
    print_summary(summary)

    print(f"\nTop {args.top} PMC papers by relevance:")
    for record in ranked_records[:args.top]:
        print(format_record(record))

    print(f"\nBottom {args.bottom} PMC papers by relevance:")
    for record in ranked_records[-args.bottom:]:
        print(format_record(record))

    print("\nCumulative relevance simulation:")
    print(f"  selection mode: {selection.selection_mode}")
    print(f"  eligible papers: {selection.eligible_count}")
    print(f"  target relevance: {args.target_relevance:.3f}")
    print(f"  min papers: {args.min_papers}")
    print(f"  max papers: {args.max_papers}")
    print(f"  min score: {args.min_score:.3f}")
    print(f"  max rank: {args.max_rank}")
    print(f"  selected papers: {len(selected)}")
    print(f"  cumulative relevance: {cumulative:.3f}")
    print("  selected PMC IDs:", ", ".join(f"PMC{record.pmc_id}" for record in selected))

    if args.json_out:
        with open(args.json_out, "w", encoding="utf8") as output_file:
            json.dump(
                {
                    "gene": args.gene,
                    "name": name,
                    "summary": summary,
                    "ranked_records": [
                        relevance_record_to_dict(record)
                        for record in ranked_records
                    ],
                },
                output_file,
                indent=2,
            )
        print(f"\nWrote ranked relevance data to {args.json_out}")

if __name__ == "__main__":
    main()