from autoannotation.pmc import PmcPaperManager, RelevanceRecord


class FakeResponse:
    def __init__(self, text):
        self.text = text


class FakeThrottler:
    def __init__(self, responses):
        self.responses = list(responses)
        self.urls = []

    def get(self, url, base_url):
        self.urls.append(url)
        return FakeResponse(self.responses.pop(0))


class FakePmcPaperManager(PmcPaperManager):
    def __init__(self, papers, sources=None):
        self.papers = papers
        self.sources = sources or {}

    def get_abstract(self, pmc_id):
        return self.papers[pmc_id].get("abstract")

    def get_results(self, pmc_id):
        return self.papers[pmc_id].get("results")

    def get_discussion(self, pmc_id):
        return self.papers[pmc_id].get("discussion")

    def get_pmid(self, pmc_id):
        return self.papers[pmc_id].get("pmid")

    def get_pmc_id_sources(self, gene, name):
        return self.sources

    def _get_title(self, pmc_id):
        return self.papers[pmc_id].get("title", "")

    def _get_publication_year(self, pmc_id):
        return self.papers[pmc_id].get("year")


class FakeSearchPmcPaperManager(PmcPaperManager):
    def __init__(self, responses):
        self.throttler = FakeThrottler(responses)


def test_get_pmc_id_sources_uses_original_pmc_search_when_idlist_is_available():
    manager = FakeSearchPmcPaperManager([
        '{"esearchresult": {"idlist": ["123"]}}',
    ])

    sources = manager.get_pmc_id_sources("Rv0003", "Rv0003")

    assert sources == {"123": {"locus"}}
    assert "db=pmc" in manager.throttler.urls[0]
    assert len(manager.throttler.urls) == 1


def test_get_pmc_id_sources_falls_back_to_pubmed_when_pmc_search_errors():
    manager = FakeSearchPmcPaperManager([
        '{"esearchresult": {"ERROR": "Search Backend failed: HTTP request returned 503 status."}}',
        '{"esearchresult": {"idlist": ["111"]}}',
        (
            '{"linksets": [{"linksetdbs": ['
            '{"linkname": "pubmed_pmc", "links": ["222"]},'
            '{"linkname": "pubmed_pmc_refs", "links": ["333"]}'
            ']}]}'
        ),
    ])

    sources = manager.get_pmc_id_sources("Rv0003", "Rv0003")

    assert sources == {"222": {"locus"}}
    assert "db=pmc" in manager.throttler.urls[0]
    assert "db=pubmed" in manager.throttler.urls[1]
    assert "elink.fcgi" in manager.throttler.urls[2]


def test_locus_title_hit_scores_above_name_only_abstract_hit():
    manager = FakePmcPaperManager(
        {
            "1": {
                "title": "Rv0001 controls replication initiation in Mycobacterium tuberculosis",
                "abstract": "This study investigates DNA replication in Mycobacterium tuberculosis.",
            },
            "2": {
                "title": "Chromosome replication proteins in bacteria",
                "abstract": "The dnaA protein is discussed in Mycobacterium tuberculosis.",
            },
        }
    )

    locus_record = manager.score_paper_relevance("1", "Rv0001", "dnaA", {"locus"})
    name_record = manager.score_paper_relevance("2", "Rv0001", "dnaA", {"name"})

    assert locus_record.score > name_record.score
    assert locus_record.evidence_flags["has_locus_hit"] is True
    assert locus_record.score_components["title_locus"] > 0


def test_excluded_species_penalty_adds_warning():
    manager = FakePmcPaperManager(
        {
            "1": {
                "title": "dnaA in Mycobacterium tuberculosis",
                "abstract": (
                    "Rv0001 dnaA is studied in Mycobacterium tuberculosis and "
                    "Mycobacterium smegmatis."
                ),
            }
        }
    )

    record = manager.score_paper_relevance("1", "Rv0001", "dnaA", {"locus", "name"})

    assert record.evidence_flags["has_excluded_species_hit"] is True
    assert record.score_components["excluded_species_penalty"] < 0
    assert "excluded_species" in record.warnings


def test_e_coli_only_gene_match_is_flagged_as_off_target():
    manager = FakePmcPaperManager(
        {
            "1": {
                "title": "dnaA replication initiation in Escherichia coli",
                "abstract": "The dnaA protein controls chromosome replication in E. coli.",
            }
        }
    )

    record = manager.score_paper_relevance("1", "Rv0001", "dnaA", {"name"})

    assert record.evidence_flags["has_target_organism_hit"] is False
    assert record.evidence_flags["has_off_target_organism_hit"] is True
    assert record.evidence_flags["is_off_target_organism_dominant"] is True
    assert "missing_target_organism" in record.warnings
    assert "off_target_organism_dominant" in record.warnings


def test_comparative_e_coli_expression_with_target_gene_evidence_remains_eligible():
    manager = FakePmcPaperManager(
        {
            "1": {
                "title": "Rv0001 dnaA from Mycobacterium tuberculosis",
                "abstract": (
                    "The Mycobacterium tuberculosis Rv0001 dnaA protein was expressed in "
                    "Escherichia coli for biochemical characterization."
                ),
            }
        }
    )

    record = manager.score_paper_relevance("1", "Rv0001", "dnaA", {"locus", "name"})
    selection = manager.select_relevance_records(
        [record], min_score=0.1, min_papers=1,
    )

    assert record.evidence_flags["has_target_organism_hit"] is True
    assert record.evidence_flags["has_off_target_organism_hit"] is True
    assert record.evidence_flags["has_strong_target_gene_evidence"] is True
    assert "off_target_organism_dominant" not in record.warnings
    assert selection.selected_records == [record]


def test_section_hits_use_section_text_not_abstract_text():
    manager = FakePmcPaperManager(
        {
            "1": {
                "title": "Tuberculosis replication study",
                "abstract": "Mycobacterium tuberculosis replication was measured.",
                "results": "The dnaA mutant had reduced growth in Mycobacterium tuberculosis.",
            }
        }
    )

    record = manager.score_paper_relevance("1", "Rv0001", "dnaA", {"name"})

    assert record.section_hits["results"]["name"] == 1
    assert record.evidence_flags["has_results_hit"] is True
    assert record.score_components["section_name"] > 0


def test_get_ranked_papers_returns_all_candidates_sorted_by_score():
    manager = FakePmcPaperManager(
        {
            "1": {
                "title": "Unrelated metabolism",
                "abstract": "Mycobacterium tuberculosis metabolism was reviewed.",
            },
            "2": {
                "title": "Rv0001 dnaA in Mycobacterium tuberculosis",
                "abstract": "Rv0001 dnaA controls replication in Mycobacterium tuberculosis.",
            },
            "3": {
                "title": "dnaA proteins",
                "abstract": "dnaA is mentioned in a broad bacterial review.",
            },
        },
        sources={
            "1": {"name"},
            "2": {"locus", "name"},
            "3": {"name"},
        },
    )

    ranked = manager.get_ranked_papers("Rv0001", "dnaA")

    assert [record.pmc_id for record in ranked] == ["2", "1", "3"]
    assert len(ranked) == 3


def test_select_papers_to_analyze_uses_ranked_records_and_cumulative_budget():
    manager = FakePmcPaperManager(
        {
            "1": {
                "title": "Rv0001 dnaA in Mycobacterium tuberculosis",
                "abstract": "Rv0001 dnaA controls replication in Mycobacterium tuberculosis.",
            },
            "2": {
                "title": "dnaA in Mycobacterium tuberculosis",
                "abstract": "dnaA is discussed in Mycobacterium tuberculosis.",
            },
            "3": {
                "title": "Unrelated review",
                "abstract": "Mycobacterium tuberculosis metabolism was reviewed.",
            },
        }
    )

    selected, cumulative = manager.select_papers_to_analyze(
        ["3", "2", "1"], "Rv0001", "dnaA",
        target_relevance=10.0, min_score=0.1, min_papers=3,
    )

    assert selected == ["1", "2", "3"]
    assert cumulative > 0


def test_select_papers_to_analyze_accepts_precomputed_ranked_records():
    manager = FakePmcPaperManager({})
    ranked_records = [
        RelevanceRecord(
            pmc_id="1",
            pmid=None,
            score=0.8,
            retrieval_sources=["locus"],
            title="",
            year=None,
            section_hits={},
            evidence_flags={},
            score_components={},
            warnings=[],
        ),
        RelevanceRecord(
            pmc_id="2",
            pmid=None,
            score=0.2,
            retrieval_sources=["name"],
            title="",
            year=None,
            section_hits={},
            evidence_flags={},
            score_components={},
            warnings=[],
        ),
    ]

    selected, cumulative = manager.select_papers_to_analyze(
        ranked_records, "Rv0001", "dnaA",
        target_relevance=1.0, min_score=0.1, min_papers=1,
    )

    assert selected == ["1"]
    assert cumulative >= 1.0


def test_selection_skips_excluded_species_records():
    manager = FakePmcPaperManager({})
    ranked_records = [
        RelevanceRecord(
            pmc_id="1",
            pmid=None,
            score=0.9,
            retrieval_sources=["locus"],
            title="",
            year=None,
            section_hits={},
            evidence_flags={"has_excluded_species_hit": True},
            score_components={},
            warnings=["excluded_species"],
        ),
        RelevanceRecord(
            pmc_id="2",
            pmid=None,
            score=0.7,
            retrieval_sources=["locus"],
            title="",
            year=None,
            section_hits={},
            evidence_flags={},
            score_components={},
            warnings=[],
        ),
    ]

    selected, cumulative = manager.select_papers_to_analyze(
        ranked_records, "Rv0001", "dnaA", target_relevance=1.0, min_score=0.1
    )

    assert selected == ["2"]
    assert cumulative >= 1.0


def test_limited_literature_selects_all_eligible_when_below_min_papers():
    manager = FakePmcPaperManager({})
    ranked_records = [
        RelevanceRecord(
            pmc_id=str(index),
            pmid=None,
            score=0.9,
            retrieval_sources=["locus"],
            title="",
            year=None,
            section_hits={},
            evidence_flags={},
            score_components={},
            warnings=[],
        )
        for index in range(1, 4)
    ]

    selection = manager.select_relevance_records(
        ranked_records, min_papers=5, target_relevance=9.0,
    )

    assert selection.selection_mode == "all_eligible_limited_literature"
    assert len(selection.selected_records) == 3
    assert selection.eligible_count == 3


def test_selection_continues_until_min_papers_even_after_target_met():
    manager = FakePmcPaperManager({})
    ranked_records = [
        RelevanceRecord(
            pmc_id=str(index),
            pmid=None,
            score=1.0,
            retrieval_sources=["locus"],
            title="",
            year=None,
            section_hits={},
            evidence_flags={},
            score_components={},
            warnings=[],
        )
        for index in range(1, 8)
    ]

    selection = manager.select_relevance_records(
        ranked_records,
        target_relevance=4.0,
        min_papers=5,
        min_score=0.1,
    )

    assert len(selection.selected_records) == 5
    assert selection.cumulative_relevance >= 4.0
    assert selection.selected_records[0].pmc_id == "1"
    assert selection.selected_records[4].pmc_id == "5"


def test_selection_respects_configurable_max_rank_boundary():
    manager = FakePmcPaperManager({})
    ranked_records = [
        RelevanceRecord(
            pmc_id=str(index),
            pmid=None,
            score=0.2,
            retrieval_sources=["name"],
            title="",
            year=None,
            section_hits={},
            evidence_flags={},
            score_components={},
            warnings=[],
        )
        for index in range(1, 22)
    ]

    selection = manager.select_relevance_records(
        ranked_records, target_relevance=10.0, min_score=0.1, max_rank=20
    )

    assert len(selection.selected_records) == 20
    assert selection.selected_records[-1].pmc_id == "20"
    assert selection.cumulative_relevance > 0
