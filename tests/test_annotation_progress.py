import json

from shared.job_progress import JobProgressEvent

from autoannotation.pmc import PaperSelectionResult, RelevanceRecord


GENE_JSON = json.dumps({
    "gene_id": "Rv0001",
    "name": "dnaA",
    "function": "Initiates DNA replication.",
    "functional_category": ["DNA replication"],
    "drug_susc_impact": "",
    "infection_impact": "",
    "essential_in_vitro": True,
    "essential_in_vivo": True,
    "annotation_notes": "Progress test notes.",
})


def test_collect_paper_sections_counts_available_parts(monkeypatch):
    from autoannotation import autoannotation as aa

    class FakePM:
        def get_abstract(self, pmc_id):
            return "abs"

        def get_results(self, pmc_id):
            return "res"

        def get_discussion(self, pmc_id):
            return "res"  # same as results → excluded

    sections = aa.collect_paper_sections(FakePM(), "1")
    assert [label for label, _ in sections] == ["abstract", "results"]


class _FakeLlmHandler:
    def get_llm_gene_info_json(
        self, gene_id, gene_name, info_text, model, section_type='abstract',
        organism_profile=None, evidence_mode='target', ortholog_context=None,
        field_defs_profile=None,
    ):
        return GENE_JSON, 0.1

    def get_llm_consensus_json(
        self, candidates, *, excerpt=None, expected_gene_id=None, expected_name=None,
        model, section_type='abstract', organism_profile=None,
        allow_missing_locus=False, field_defs_profile=None,
    ):
        return GENE_JSON, 0.1

    @staticmethod
    def json_regex_filter(gene_json, organism_profile=None, expected_gene=None, relaxed_name=False):
        return True

    def get_llm_aggregate_json(
        self, json_responses, pmids, model, literature_context=None, relevance_scores=None,
        organism_profile=None, allow_missing_locus=False,
        evidence_mode='target', ortholog_context=None, field_defs_profile=None,
    ):
        return GENE_JSON, 0.1


class _FakePaperManager:
    def get_ranked_papers(self, gene, name):
        return [
            RelevanceRecord(
                pmc_id="1",
                pmid="12345",
                score=0.8,
                retrieval_sources=["locus"],
                title="Rv0001 dnaA",
                year=2020,
                section_hits={},
                evidence_flags={},
                score_components={},
                warnings=[],
            )
        ]

    def save_gene_pmc_ids(self, gene, pmc_ids):
        pass

    def select_relevance_records(self, records, **kwargs):
        return PaperSelectionResult(
            selected_records=records,
            cumulative_relevance=1.6,
            selection_mode="all_eligible_limited_literature",
            eligible_count=len(records),
            total_retrieved=len(records),
        )

    def get_abstract(self, pmc_id):
        return "Rv0001 dnaA initiates replication."

    def get_results(self, pmc_id):
        return None

    def get_discussion(self, pmc_id):
        return None

    def get_pmid(self, pmc_id):
        return "12345"


def test_run_paper_annotation_pass_emits_fetch_then_extract_totals(monkeypatch):
    from autoannotation import autoannotation as aa

    events: list[JobProgressEvent] = []

    aa.run_paper_annotation_pass(
        "Rv0001",
        "dnaA",
        "Rv0001",
        None,
        llm_handler=_FakeLlmHandler(),
        paper_manager=_FakePaperManager(),
        cache_key=None,
        progress_cb=events.append,
    )

    assert events, "expected at least one progress event"
    for event in events:
        assert isinstance(event, JobProgressEvent)

    # Section totals must be known before any LLM call happens (i.e. by the
    # time we see the first "extracting" event, which precedes the section
    # loop that invokes the LLM handler).
    extracting_events = [e for e in events if e.phase == "extracting"]
    assert extracting_events, "expected an extracting phase event"
    assert extracting_events[0].sections_total == 1
    assert extracting_events[0].sections_done == 0
    assert extracting_events[0].pass_name == "target"

    # sections_done increments after consensus for the single abstract section.
    assert extracting_events[-1].sections_done == 1

    # aggregating phase emitted before the aggregate call.
    aggregating_events = [e for e in events if e.phase == "aggregating"]
    assert aggregating_events
    assert aggregating_events[0].pass_name == "target"

    # extracting comes strictly before aggregating.
    extracting_idx = events.index(extracting_events[0])
    aggregating_idx = events.index(aggregating_events[0])
    assert extracting_idx < aggregating_idx
