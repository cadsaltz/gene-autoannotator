"""
run with:

python -m run_pipeline 2>&1 | tee log.txt

"""

# Manual evaluation harness (not the normal app entry point). Runs a fixed
# benchmark gene list, compares generated JSON against trusted fixtures, and
# appends scores to pipeline_scores.jsonl.
import json
import time
import os
from datetime import datetime
import traceback

COMPLETE_LOG = "completed_genes.txt"
ERROR_LOG = "error_log.txt"
SCORES_LOG = "pipeline_scores.jsonl"


def record_result(
    gene,
    comparison_result,
    duration,
    num_papers_used,
    num_total_papers,
    cumulative_relevance=0.0,
):
    record = {
        "timestamp": datetime.now().isoformat(),
        "gene": gene,
        "comparison_result": comparison_result,
        "duration": duration,
        "num_papers_used": num_papers_used,
        "num_total_papers": num_total_papers,
        "cumulative_relevance": cumulative_relevance,
    }
    with open(SCORES_LOG, "a") as f:
        f.write(json.dumps(record) + "\n")
    print(f"Score recorded: {gene}")


def mark_complete(gene):
    with open(COMPLETE_LOG, "a") as f:
        f.write(gene + "\n")
    print(f"Completed {gene}")


def log_error(gene, error):
    timestamp = datetime.now().isoformat()
    error_message = (
        f"\n[{timestamp}] ERROR processing {gene}\n"
        f"{str(error)}\n"
        f"{traceback.format_exc()}\n"
        f"{'='*60}\n"
    )
    with open(ERROR_LOG, "a") as f:
        f.write(error_message)
    print(f"Error processing {gene}")
    print(error)


def load_completed_genes():
    if not os.path.exists(COMPLETE_LOG):
        return set()
    with open(COMPLETE_LOG, "r") as f:
        return set(line.strip() for line in f)


GENES = [
    "Rv0001",
    "Rv0002",
    "Rv0003",
    "Rv2007c",
    "Rv2057c",
    "Rv2070c",
    "Rv2418c",
    "Rv2612c",
    "Rv3221A",
    "Rv3459c",
]


def main():
    from autoannotation.__main__ import main as annotate
    from compareannotations.__main__ import main as compare

    completed_genes = load_completed_genes()
    # completed_genes.txt makes long benchmark runs resumable after model/API
    # failures; deleting it intentionally reruns the full fixed list.
    for gene in GENES:
        if gene in completed_genes:
            print(f"Skipping {gene}: already completed")
            continue
        try:
            print(f"\nStarting {gene}")
            start = time.time()
            annotation_result = annotate(gene)
            if annotation_result is None:
                print(f"Skipping {gene}: annotation failed")
                record_result(gene, "N/A", "N/A", 0, "N/A")
                continue
            papers_used = annotation_result["papers_used"]
            total_papers = annotation_result["all_papers"]
            generated_json = annotation_result["output_path"]
            cumulative_relevance = annotation_result["cumulative_relevance"]
            trusted_json = os.path.join("trust_json", f"trust_{gene}.json")
            duration = time.time() - start
            print(f"\nComparing {gene}: {trusted_json} vs {generated_json}")
            comparison_result = compare(trusted_json, generated_json)
            record_result(
                gene,
                comparison_result,
                duration,
                len(papers_used),
                len(total_papers),
                cumulative_relevance,
            )
            mark_complete(gene)
        except Exception as e:
            log_error(gene, e)
            continue


if __name__ == "__main__":
    main()
