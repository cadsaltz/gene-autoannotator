from autoannotation import metadata
from autoannotation.organisms import resolve_profile


def test_empty_annotation_null_fields_and_notes():
    profile = resolve_profile("mtb-h37rv")
    meta = {"profile_id": "mtb-h37rv", "quality_flags": ["no_papers_analyzed"]}
    doc = metadata.empty_annotation_from_metadata(
        meta, gene_id="Rv9999", name="fake", profile=profile,
    )
    assert doc["gene_id"] == "Rv9999"
    assert doc["function"] is None
    assert doc["functional_category"] is None
    assert doc["annotation_notes"] == metadata.EMPTY_TARGET_NOTES
    assert doc["annotation_metadata"]["field_coverage"]["function"] == "insufficient_evidence"


def test_get_gene_annotation_seeds_blank_when_target_has_no_papers(monkeypatch):
    import autoannotation.autoannotation as aa

    class FakePass:
        gene_distillation = None
        ranked_papers = []
        selection = type("S", (), {
            "selected_records": [],
            "selection_mode": "all_eligible_limited_literature",
            "eligible_count": 0,
        })()
        used_pmc_ids = []
        pmids_analyzed = []
        sections_analyzed = 0
        cumulative_relevance = 0.0

    monkeypatch.setattr(aa, "run_paper_annotation_pass", lambda *a, **k: FakePass())
    monkeypatch.setattr(
        aa, "_decide_ortholog_action",
        lambda **k: aa.OrthologDecision(hit=None, skipped_reason="fallback_disabled_for_job"),
    )
    result = aa.get_gene_annotation(
        profile="mtb-h37rv", locus="Rv9999",
        allow_online_name_lookup=False, allow_ortholog_fallback=False,
    )
    assert result["gene_annotation"] is not None
    assert result["gene_annotation"]["function"] is None
    assert result["used_ids"] == []


def test_blank_target_still_requests_ortholog_when_relevance_is_zero(monkeypatch):
    import autoannotation.autoannotation as aa
    seen = {}

    class FakePass:
        gene_distillation = None
        ranked_papers = []
        selection = type("S", (), {
            "selected_records": [],
            "selection_mode": "all_eligible_limited_literature",
            "eligible_count": 0,
        })()
        used_pmc_ids = []
        pmids_analyzed = []
        sections_analyzed = 0
        cumulative_relevance = 0.0

    def fake_decide(**kwargs):
        seen["cumulative_relevance"] = kwargs["cumulative_relevance"]
        seen["allow"] = kwargs["allow_ortholog_fallback"]
        return aa.OrthologDecision(hit=None, skipped_reason="no_ortholog_found")

    monkeypatch.setattr(aa, "run_paper_annotation_pass", lambda *a, **k: FakePass())
    monkeypatch.setattr(aa, "_decide_ortholog_action", fake_decide)
    result = aa.get_gene_annotation(
        profile="mtb-h37rv", locus="Rv9999",
        allow_online_name_lookup=False, allow_ortholog_fallback=True,
    )
    assert seen["allow"] is True
    assert seen["cumulative_relevance"] == 0.0
    assert result["gene_annotation"] is not None
    # Must not skip as no_eligible_fields solely because target was empty
    assert result["gene_annotation"]["annotation_metadata"]["ortholog_pass"]["skipped_reason"] != "no_eligible_fields"


def test_blank_target_appends_empty_ortholog_notes_when_ortholog_has_no_papers(monkeypatch):
    import autoannotation.autoannotation as aa
    from autoannotation.orthology import OrthologHit

    class FakePass:
        gene_distillation = None
        ranked_papers = []
        selection = type("S", (), {
            "selected_records": [],
            "selection_mode": "all_eligible_limited_literature",
            "eligible_count": 0,
        })()
        used_pmc_ids = []
        pmids_analyzed = []
        sections_analyzed = 0
        cumulative_relevance = 0.0

    hit = OrthologHit(
        source_organism_code="mory",
        source_organism_name="Mycobacterium orygis",
        source_gene_id="MO_000001",
        source_gene_name="dnaA",
        score=507.0,
        identity=0.82,
        lookup_source="kegg_ssdb",
    )

    monkeypatch.setattr(aa, "run_paper_annotation_pass", lambda *a, **k: FakePass())
    monkeypatch.setattr(
        aa, "_decide_ortholog_action",
        lambda **k: aa.OrthologDecision(hit=hit, skipped_reason=None),
    )
    result = aa.get_gene_annotation(
        profile="mtb-h37rv", locus="Rv9999",
        allow_online_name_lookup=False, allow_ortholog_fallback=True,
    )
    notes = result["gene_annotation"]["annotation_notes"]
    assert metadata.EMPTY_TARGET_NOTES in notes
    assert metadata.EMPTY_ORTHOLOG_NOTES in notes
    assert result["gene_annotation"]["annotation_metadata"]["ortholog_pass"]["skipped_reason"] == "no_ortholog_papers"
