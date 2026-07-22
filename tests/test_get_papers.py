from autoannotation.pmc import RelevanceRecord
from get_papers import summarize_ranked_records


def make_record(pmc_id, score, sources, warnings=None):
    return RelevanceRecord(
        pmc_id=pmc_id,
        pmid=f"PMID{pmc_id}",
        score=score,
        retrieval_sources=sources,
        title=f"Title {pmc_id}",
        year=2020,
        section_hits={},
        evidence_flags={},
        score_components={"component": score},
        warnings=warnings or [],
    )


def test_summarize_ranked_records_reports_counts_and_score_distribution():
    records = [
        make_record("1", 0.9, ["locus", "name"]),
        make_record("2", 0.55, ["name"], ["name_only_match"]),
        make_record("3", 0.05, ["name"], ["missing_organism"]),
    ]

    summary = summarize_ranked_records(records)

    assert summary["total"] == 3
    assert summary["retrieval_sources"]["locus"] == 1
    assert summary["retrieval_sources"]["name"] == 3
    assert summary["score"]["max"] == 0.9
    assert summary["score"]["min"] == 0.05
    assert summary["score"]["above_0_75"] == 1
    assert summary["score"]["above_0_50"] == 2
    assert summary["score"]["below_0_10"] == 1
    assert summary["warnings"]["name_only_match"] == 1
    assert summary["warnings"]["missing_organism"] == 1
