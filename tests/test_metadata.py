import json

from autoannotation import metadata
from autoannotation.pmc import RelevanceRecord


def make_record(pmc_id, score, warnings=None):
    return RelevanceRecord(
        pmc_id=pmc_id,
        pmid=f"PMID{pmc_id}",
        score=score,
        retrieval_sources=["locus"],
        title=f"Title {pmc_id}",
        year=2020,
        section_hits={},
        evidence_flags={},
        score_components={},
        warnings=warnings or [],
    )


def test_filter_eligible_records_excludes_low_score_and_excluded_species():
    records = [
        make_record("1", 0.8),
        make_record("2", 0.05),
        make_record("3", 0.7, warnings=["excluded_species"]),
    ]

    eligible = metadata.filter_eligible_records(records)

    assert [record.pmc_id for record in eligible] == ["1"]


def test_filter_eligible_records_excludes_target_organism_warnings():
    records = [
        make_record("1", 0.8),
        make_record("2", 0.8, warnings=["missing_target_organism"]),
        make_record("3", 0.8, warnings=["off_target_organism_dominant"]),
    ]

    eligible = metadata.filter_eligible_records(records)

    assert [record.pmc_id for record in eligible] == ["1"]


def test_merge_annotation_output_adds_metadata_and_preserves_notes():
    gene_json = json.dumps({
        "rv_id": "Rv0001",
        "name": "dnaA",
        "function": "test",
        "functional_category": ["DNA replication"],
        "drug_susc_impact": "",
        "infection_impact": "",
        "essential_in_vitro": True,
        "essential_in_vivo": True,
        "annotation_notes": "Analyzed five papers with strong support.",
    })
    annotation_metadata = {"selection_mode": "cumulative_relevance_budget"}

    merged = metadata.merge_annotation_output(
        gene_json,
        annotation_metadata,
        field_coverage={"function": "supported"},
    )

    assert merged["annotation_notes"] == "Analyzed five papers with strong support."
    assert merged["annotation_metadata"]["selection_mode"] == "cumulative_relevance_budget"
    assert merged["annotation_metadata"]["field_coverage"]["function"] == "supported"


def test_build_literature_context_mentions_selected_paper_count():
    ranked = [make_record(str(i), 0.9 - i * 0.1) for i in range(6)]
    selected = ranked[:3]

    context = metadata.build_literature_context_for_notes(
        ranked_records=ranked,
        selected_records=selected,
        selection_mode=metadata.SELECTION_MODE_BUDGET,
        eligible_count=6,
        cumulative_relevance=4.5,
        target_relevance=9.0,
        min_papers=5,
    )

    assert "Papers selected for analysis: 3" in context
    assert "PMC0" in context
    assert "annotation_notes" in context


def test_build_annotation_metadata_includes_profile_fields():
    record = make_record("1", 0.8)

    annotation_metadata = metadata.build_annotation_metadata(
        gene="TcCLB.503799.4",
        gene_name="TcCLB.503799.4",
        ranked_records=[record],
        selected_records=[record],
        analyzed_pmc_ids=["1"],
        pmids_analyzed=["PMID1"],
        sections_analyzed=1,
        selection_mode=metadata.SELECTION_MODE_LIMITED,
        eligible_count=1,
        cumulative_relevance=1.6,
        target_relevance=9.0,
        min_papers=5,
        max_papers=20,
        duration_sec=2.0,
        profile_id="tcruzi-clbrener",
        canonical_name="Trypanosoma cruzi CL Brener",
        species_name="Trypanosoma cruzi",
        strain="CL Brener",
        gene_name_source="manual_cache",
        gene_name_source_detail="Curated from literature",
        gene_name_candidates=["TcUBP1"],
        gene_name_confidence="curated",
        gene_name_aliases=["UBP1"],
        gene_name_warnings=[],
    )

    assert annotation_metadata["profile_id"] == "tcruzi-clbrener"
    assert annotation_metadata["canonical_name"] == "Trypanosoma cruzi CL Brener"
    assert annotation_metadata["species_name"] == "Trypanosoma cruzi"
    assert annotation_metadata["strain"] == "CL Brener"
    assert annotation_metadata["gene_name_source"] == "manual_cache"
    assert annotation_metadata["gene_name_source_detail"] == "Curated from literature"
    assert annotation_metadata["gene_name_candidates"] == ["TcUBP1"]
    assert annotation_metadata["gene_name_confidence"] == "curated"
    assert annotation_metadata["gene_name_aliases"] == ["UBP1"]


def test_fields_eligible_for_ortholog_returns_all_allowed_in_schema():
    from autoannotation import field_defs, metadata, organisms

    profile = organisms.resolve_profile("mtb-h37rv")
    defs = field_defs.resolve_annotation_field_defs(profile)
    # Eligible ortholog fields follow the live profile's ortholog_allowed flags.
    eligible = metadata.fields_eligible_for_ortholog(defs)
    expected = {
        d.key for d in defs
        if d.ortholog_allowed and field_defs.include_in_llm_schema(d)
    }
    assert set(eligible) == expected
    assert "function" in eligible
    for key in eligible:
        matching = next(d for d in defs if d.key == key)
        assert matching.ortholog_allowed is True
        assert field_defs.include_in_llm_schema(matching)


def test_fields_eligible_for_ortholog_excludes_out_of_schema_fields():
    from autoannotation import field_defs, metadata

    in_schema = field_defs.AnnotationFieldDef(
        key="function",
        label="Function",
        description="",
        type="string",
        required=True,
        inference_strategy="paper_llm",
        ortholog_allowed=True,
    )
    # ortholog_allowed but excluded from the LLM schema: a non-paper_llm strategy
    # whose key is not the special-cased `functional_category`.
    out_of_schema = field_defs.AnnotationFieldDef(
        key="go_derived_field",
        label="GO-derived field",
        description="",
        type="array:string",
        required=False,
        inference_strategy="go_terms",
        ortholog_allowed=True,
    )
    assert field_defs.include_in_llm_schema(in_schema) is True
    assert field_defs.include_in_llm_schema(out_of_schema) is False

    eligible = metadata.fields_eligible_for_ortholog([in_schema, out_of_schema])

    assert eligible == ["function"]


def test_annotation_metadata_records_submitted_and_resolved_target_fields():
    annotation_metadata = metadata.build_annotation_metadata(
        gene=None,
        gene_name="abc1",
        ranked_records=[],
        selected_records=[],
        analyzed_pmc_ids=[],
        pmids_analyzed=[],
        sections_analyzed=0,
        selection_mode="all_eligible_limited_literature",
        eligible_count=0,
        cumulative_relevance=0,
        target_relevance=9,
        min_papers=5,
        max_papers=20,
        duration_sec=1,
        profile_id="ad-hoc-custom",
        canonical_name="Custom bacterium",
        species_name="Custom bacterium",
        target_warnings=["ad_hoc_profile", "missing_locus"],
        submitted_locus=None,
        submitted_name="abc1",
        resolved_locus=None,
        resolved_name="abc1",
        profile_source="ad_hoc",
    )

    assert annotation_metadata["submitted_locus"] is None
    assert annotation_metadata["submitted_name"] == "abc1"
    assert annotation_metadata["resolved_name"] == "abc1"
    assert annotation_metadata["profile_source"] == "ad_hoc"
    assert annotation_metadata["target_warnings"] == ["ad_hoc_profile", "missing_locus"]
