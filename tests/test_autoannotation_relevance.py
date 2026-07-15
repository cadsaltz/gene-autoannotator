import json

import pandas as pd
import pytest

from autoannotation import autoannotation
from autoannotation import organisms
from autoannotation.orthology import OrthologHit
from autoannotation.pmc import PaperSelectionResult, RelevanceRecord


GENE_JSON = json.dumps({
    "gene_id": "Rv0001",
    "name": "dnaA",
    "function": None,
    "functional_category": ["DNA replication"],
    "drug_susc_impact": "",
    "infection_impact": "",
    "essential_in_vitro": True,
    "essential_in_vivo": True,
    "annotation_notes": "Direct pass with missing function.",
})

GENE_JSON_COMPLETE = json.dumps({
    "gene_id": "Rv0001",
    "name": "dnaA",
    "function": "Initiates DNA replication.",
    "functional_category": ["DNA replication"],
    "drug_susc_impact": "",
    "infection_impact": "",
    "essential_in_vitro": True,
    "essential_in_vivo": True,
    "annotation_notes": "Direct pass complete.",
})

ORTHolog_JSON = json.dumps({
    "gene_id": "MO_000001",
    "name": "dnaA",
    "function": "Initiates DNA replication in M. orygis.",
    "functional_category": ["DNA replication"],
    "drug_susc_impact": None,
    "infection_impact": None,
    "essential_in_vitro": None,
    "essential_in_vivo": None,
    "annotation_notes": "Ortholog pass notes.",
})

TCRUZI_JSON = json.dumps({
    "gene_id": "TcCLB.503799.4",
    "name": "TcCLB.503799.4",
    "function": "Surface protein.",
    "functional_category": ["host interaction"],
    "drug_susc_impact": None,
    "infection_impact": "May affect infection.",
    "essential_in_vitro": None,
    "essential_in_vivo": None,
    "annotation_notes": "Analyzed one T. cruzi paper.",
})


class FakeLlmHandler:
    def __init__(self, cache_dir):
        self.cache_dir = cache_dir
        self.aggregate_calls = 0

    @staticmethod
    def json_regex_filter(gene_json, organism_profile=None, expected_gene=None, relaxed_name=False):
        assert expected_gene in {"Rv0001", "MO_000001", "TcCLB.503799.4", "Rv2007c", None}
        return True

    def get_llm_gene_info_json(
        self, gene_id, gene_name, info_text, model, section_type='abstract',
        organism_profile=None, evidence_mode='target', ortholog_context=None,
        field_defs_profile=None,
    ):
        assert section_type == 'abstract'
        if evidence_mode == 'ortholog':
            assert ortholog_context is not None
            return ORTHolog_JSON, 0.1
        if gene_id and gene_id.startswith("TcCLB"):
            return TCRUZI_JSON, 0.1
        return GENE_JSON, 0.1

    def get_llm_consensus_json(
        self, candidates, *, excerpt=None, expected_gene_id=None, expected_name=None,
        model, section_type='abstract', organism_profile=None,
        allow_missing_locus=False, field_defs_profile=None,
    ):
        assert section_type == 'abstract'
        json1 = candidates[0]
        if json1 == ORTHolog_JSON:
            return ORTHolog_JSON, 0.1
        if '"TcCLB' in json1:
            return TCRUZI_JSON, 0.1
        return GENE_JSON, 0.1

    def get_llm_aggregate_json(
        self, json_responses, pmids, model, literature_context=None, relevance_scores=None,
        organism_profile=None, allow_missing_locus=False,
        evidence_mode='target', ortholog_context=None, field_defs_profile=None,
    ):
        assert literature_context is not None
        assert relevance_scores is not None
        self.aggregate_calls += 1
        if evidence_mode == 'ortholog':
            assert ortholog_context is not None
            return ORTHolog_JSON, 0.1
        if organism_profile and organism_profile.profile_id == "tcruzi-clbrener":
            return TCRUZI_JSON, 0.1
        if self.aggregate_calls == 1:
            return GENE_JSON, 0.1
        return GENE_JSON_COMPLETE, 0.1

    def summarize_usage(self):
        return {
            "calls": 5,
            "cache_hits": 0,
            "known_input_tokens": 100,
            "known_output_tokens": 25,
            "known_total_tokens": 125,
            "usage_records_with_missing_tokens": 0,
            "by_role": {},
            "by_model": {},
        }


class FakePmcPaperManager:
    def __init__(self, cache_dir, organism_profile=None):
        self.cache_dir = cache_dir
        self.organism_profile = organism_profile

    def get_ranked_papers(self, gene, name):
        if gene == 'MO_000001':
            return [
                RelevanceRecord(
                    pmc_id="99",
                    pmid="99999",
                    score=0.85,
                    retrieval_sources=["locus"],
                    title="MO_000001 dnaA in Mycobacterium orygis",
                    year=2020,
                    section_hits={},
                    evidence_flags={},
                    score_components={},
                    warnings=[],
                )
            ]
        if gene and gene.startswith("TcCLB"):
            return [
                RelevanceRecord(
                    pmc_id="2",
                    pmid="54321",
                    score=0.85,
                    retrieval_sources=["locus"],
                    title="TcCLB.503799.4 in Trypanosoma cruzi",
                    year=2021,
                    section_hits={},
                    evidence_flags={},
                    score_components={},
                    warnings=[],
                )
            ]
        return [
            RelevanceRecord(
                pmc_id="1",
                pmid="12345",
                score=0.8,
                retrieval_sources=["locus"],
                title="Rv0001 dnaA in Mycobacterium tuberculosis",
                year=2020,
                section_hits={},
                evidence_flags={},
                score_components={},
                warnings=[],
            )
        ]

    def save_gene_pmc_ids(self, gene, pmc_ids):
        self.saved_ids = pmc_ids

    def select_relevance_records(self, records, **kwargs):
        return PaperSelectionResult(
            selected_records=records,
            cumulative_relevance=1.6,
            selection_mode="all_eligible_limited_literature",
            eligible_count=len(records),
            total_retrieved=len(records),
        )

    def get_abstract(self, pmc_id):
        if pmc_id == "99":
            return "MO_000001 dnaA in Mycobacterium orygis."
        if pmc_id == "2":
            return "TcCLB.503799.4 is discussed in Trypanosoma cruzi."
        return "Rv0001 dnaA initiates replication in Mycobacterium tuberculosis."

    def get_results(self, pmc_id):
        return None

    def get_discussion(self, pmc_id):
        return None

    def get_pmid(self, pmc_id):
        return {"1": "12345", "2": "54321", "99": "99999"}.get(pmc_id, "12345")


def _patch_common(monkeypatch, tmp_path):
    mycobrowser_df = pd.DataFrame([
        {"Feature": "CDS", "Locus": "Rv0001", "Name": "dnaA"}
    ])
    monkeypatch.setattr(
        autoannotation.organisms.gene_names.pd,
        "read_csv",
        lambda *args, **kwargs: mycobrowser_df,
    )
    monkeypatch.setattr(autoannotation.llms, "LlmHandler", FakeLlmHandler)
    monkeypatch.setattr(autoannotation.pmc, "PmcPaperManager", FakePmcPaperManager)


def test_get_gene_annotation_consumes_ranked_relevance_records(monkeypatch, tmp_path):
    _patch_common(monkeypatch, tmp_path)
    monkeypatch.setattr(
        autoannotation.orthology,
        'lookup_best_profiled_ortholog',
        lambda *args, **kwargs: OrthologHit(
            source_organism_code='mory',
            source_organism_name='Mycobacterium orygis',
            source_gene_id='MO_000001',
            source_gene_name='dnaA',
            score=507.0,
            identity=0.82,
            lookup_source='kegg_ssdb',
        ),
    )

    result = autoannotation.get_gene_annotation(
        "Rv0001", cache_dir=tmp_path, allow_ortholog_fallback=True,
    )

    assert result["used_ids"] == ["1"]
    meta = result["gene_annotation"]["annotation_metadata"]
    assert meta["ortholog_top_hit"]["source_gene_id"] == "MO_000001"
    assert meta["ortholog_pass"]["ran"] is True
    assert result["gene_annotation"]["function"] == "Initiates DNA replication in M. orygis."
    assert meta["field_provenance"]["function"] == "ortholog_derived"
    assert meta["review_flags"]["function"] is True


def test_get_gene_annotation_skips_ortholog_when_fallback_disabled(monkeypatch, tmp_path):
    _patch_common(monkeypatch, tmp_path)

    called = {"lookup": False}

    def fake_lookup(*args, **kwargs):
        called["lookup"] = True
        return OrthologHit(
            source_organism_code='mory',
            source_organism_name='Mycobacterium orygis',
            source_gene_id='MO_000001',
            source_gene_name='dnaA',
            score=507.0,
            identity=0.82,
            lookup_source='kegg_ssdb',
        )

    monkeypatch.setattr(autoannotation.orthology, 'lookup_best_profiled_ortholog', fake_lookup)

    result = autoannotation.get_gene_annotation("Rv0001", cache_dir=tmp_path)
    meta = result["gene_annotation"]["annotation_metadata"]

    assert called["lookup"] is False
    assert meta["ortholog_top_hit"] is None
    assert meta["ortholog_pass"]["ran"] is False
    assert meta["ortholog_pass"]["skipped_reason"] == "fallback_disabled_for_job"
    assert result["gene_annotation"]["function"] is None


def test_get_gene_annotation_skips_ortholog_when_relevance_sufficient(monkeypatch, tmp_path):
    _patch_common(monkeypatch, tmp_path)

    class HighRelevancePaperManager(FakePmcPaperManager):
        def select_relevance_records(self, records, **kwargs):
            return PaperSelectionResult(
                selected_records=records,
                cumulative_relevance=9.5,
                selection_mode="target_relevance_reached",
                eligible_count=len(records),
                total_retrieved=len(records),
            )

    monkeypatch.setattr(autoannotation.pmc, "PmcPaperManager", HighRelevancePaperManager)

    called = {"lookup": False}

    def fake_lookup(*args, **kwargs):
        called["lookup"] = True
        return object()

    monkeypatch.setattr(autoannotation.orthology, 'lookup_best_profiled_ortholog', fake_lookup)

    result = autoannotation.get_gene_annotation(
        "Rv0001", cache_dir=tmp_path, allow_ortholog_fallback=True,
    )
    meta = result["gene_annotation"]["annotation_metadata"]

    assert called["lookup"] is False
    assert meta["ortholog_top_hit"] is None
    assert meta["ortholog_pass"]["ran"] is False
    assert meta["ortholog_pass"]["skipped_reason"] == "target_relevance_sufficient"


def test_get_gene_annotation_survives_kegg_lookup_failure(monkeypatch, tmp_path):
    _patch_common(monkeypatch, tmp_path)
    monkeypatch.setattr(
        autoannotation.orthology, 'lookup_best_profiled_ortholog', lambda *args, **kwargs: None
    )

    result = autoannotation.get_gene_annotation(
        "Rv0001", cache_dir=tmp_path, allow_ortholog_fallback=True,
    )

    assert result["gene_annotation"] is not None
    assert result["gene_annotation"]["annotation_metadata"]["ortholog_top_hit"] is None
    assert result["gene_annotation"]["annotation_metadata"]["ortholog_pass"]["skipped_reason"] == (
        "no_profiled_ortholog"
    )


def test_get_gene_annotation_accepts_tcruzi_profile_without_table(monkeypatch, tmp_path):
    monkeypatch.setattr(autoannotation.llms, "LlmHandler", FakeLlmHandler)
    monkeypatch.setattr(autoannotation.pmc, "PmcPaperManager", FakePmcPaperManager)

    result = autoannotation.get_gene_annotation(
        profile="tcruzi-clbrener",
        locus="TcCLB.503799.4",
        gene_name_cache_dir=tmp_path,
        allow_online_name_lookup=False,
        cache_dir=tmp_path,
    )

    assert result["used_ids"] == ["2"]
    assert result["gene_annotation"]["gene_id"] == "TcCLB.503799.4"


def test_mtb_profile_has_kegg_organism_code():
    profile = organisms.resolve_profile('mtb-h37rv')
    assert profile.kegg_organism_code == 'mtu'


def test_name_only_ad_hoc_annotation_uses_safe_profile_aware_mapping_key(monkeypatch, tmp_path):
    captured = {}

    class FakeNameOnlyPaperManager:
        def __init__(self, cache_dir, organism_profile=None):
            captured["profile_id"] = organism_profile.profile_id

        def get_ranked_papers(self, gene, name):
            captured["gene"] = gene
            captured["name"] = name
            return []

        def save_gene_pmc_ids(self, gene, pmc_ids):
            captured["saved_gene"] = gene
            captured["pmc_ids"] = pmc_ids

        def select_relevance_records(self, records, **kwargs):
            return PaperSelectionResult(
                selected_records=[],
                cumulative_relevance=0.0,
                selection_mode="all_eligible_limited_literature",
                eligible_count=0,
                total_retrieved=0,
            )

        def get_pmid(self, pmc_id):
            return None

    monkeypatch.setattr(autoannotation.llms, "LlmHandler", FakeLlmHandler)
    monkeypatch.setattr(autoannotation.pmc, "PmcPaperManager", FakeNameOnlyPaperManager)

    result = autoannotation.get_gene_annotation(
        organism="Custom bacterium",
        name="../unsafe/name",
        cache_dir=tmp_path,
        allow_online_name_lookup=False,
    )

    assert captured["gene"] is None
    assert captured["name"] == "../unsafe/name"
    assert captured["saved_gene"] != "../unsafe/name"
    assert "/" not in captured["saved_gene"]
    assert ".." not in captured["saved_gene"]
    assert captured["profile_id"] in captured["saved_gene"]
    assert result["annotation_metadata"]["gene"] is None


def test_ortholog_skipped_when_fallback_disabled(monkeypatch):
    from autoannotation import autoannotation as aa

    called = {"lookup": False}

    def fake_lookup(*args, **kwargs):
        called["lookup"] = True
        return None

    monkeypatch.setattr(aa.orthology, "lookup_best_profiled_ortholog", fake_lookup)
    reason = aa._decide_ortholog_action(
        allow_ortholog_fallback=False,
        ortholog_override=None,
        cumulative_relevance=0.0,
        kegg_code="mtu",
        gene="Rv0001",
        cache_dir="./.cache",
    )
    assert reason.hit is None
    assert reason.skipped_reason == "fallback_disabled_for_job"
    assert called["lookup"] is False


def test_ortholog_skipped_when_relevance_sufficient(monkeypatch):
    from autoannotation import autoannotation as aa

    monkeypatch.setattr(
        aa.orthology, "lookup_best_profiled_ortholog", lambda *a, **k: object()
    )
    reason = aa._decide_ortholog_action(
        allow_ortholog_fallback=True,
        ortholog_override=None,
        cumulative_relevance=aa.pmc.DEFAULT_TARGET_RELEVANCE + 1,
        kegg_code="mtu",
        gene="Rv0001",
        cache_dir="./.cache",
    )
    assert reason.hit is None
    assert reason.skipped_reason == "target_relevance_sufficient"


def test_ortholog_manual_override_bypasses_relevance(monkeypatch):
    from autoannotation import autoannotation as aa

    sentinel = object()
    monkeypatch.setattr(aa.orthology, "build_manual_ortholog_hit", lambda *a, **k: sentinel)
    override = {"profile_id": "mtb-h37rv", "locus": "Rv9999", "name": "x"}
    reason = aa._decide_ortholog_action(
        allow_ortholog_fallback=True,
        ortholog_override=override,
        cumulative_relevance=aa.pmc.DEFAULT_TARGET_RELEVANCE + 100,
        kegg_code="mtu",
        gene="Rv0001",
        cache_dir="./.cache",
    )
    assert reason.hit is sentinel
    assert reason.skipped_reason is None


def test_ortholog_manual_override_resolves_non_mtb_profile():
    from autoannotation import autoannotation as aa

    override = {"profile_id": "tcruzi-clbrener", "locus": "TcCLB.1", "name": "geneA"}
    decision = aa._decide_ortholog_action(
        allow_ortholog_fallback=True,
        ortholog_override=override,
        cumulative_relevance=aa.pmc.DEFAULT_TARGET_RELEVANCE + 100,
        kegg_code="mtu",
        gene="Rv0001",
        cache_dir="./.cache",
    )
    assert decision.hit.lookup_source == "manual"
    assert decision.hit.source_gene_id == "TcCLB.1"
    search_profile = aa.orthology.profile_for_kegg_organism(decision.hit.source_organism_code)
    assert "Trypanosoma cruzi" in search_profile.species_name


def test_ortholog_profile_only_override_restricts_automatic_lookup(monkeypatch):
    from autoannotation import autoannotation as aa

    captured = {}
    sentinel = object()

    def fake_lookup(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return sentinel

    monkeypatch.setattr(aa.orthology, "lookup_best_profiled_ortholog", fake_lookup)
    monkeypatch.setattr(
        aa,
        "_resolve_profile_from_catalog",
        lambda profile_id, **kwargs: type(
            "P",
            (),
            {"kegg_organism_code": "mory", "profile_id": profile_id},
        )(),
    )

    decision = aa._decide_ortholog_action(
        allow_ortholog_fallback=True,
        ortholog_override={"profile_id": "mory"},
        cumulative_relevance=0.0,
        kegg_code="mtu",
        gene="Rv0001",
        cache_dir="./.cache",
    )
    assert decision.hit is sentinel
    assert decision.skipped_reason is None
    assert captured["kwargs"]["restrict_to_organism_code"] == "mory"


def test_ortholog_decide_transforms_kegg_locus_before_lookup(monkeypatch):
    from autoannotation import autoannotation as aa

    captured = {}

    def fake_lookup(kegg_code, gene_locus, **kwargs):
        captured["kegg_code"] = kegg_code
        captured["gene_locus"] = gene_locus
        return object()

    monkeypatch.setattr(aa.orthology, "lookup_best_profiled_ortholog", fake_lookup)

    decision = aa._decide_ortholog_action(
        allow_ortholog_fallback=True,
        ortholog_override=None,
        cumulative_relevance=0.0,
        kegg_code="tcr",
        gene="TcCLB.507297.10",
        cache_dir="./.cache",
        kegg_locus_regex=r"^TcCLB\.(.+)$",
    )
    assert decision.hit is not None
    assert captured["kegg_code"] == "tcr"
    assert captured["gene_locus"] == "507297.10"


def test_ortholog_profile_only_override_still_gates_on_relevance(monkeypatch):
    from autoannotation import autoannotation as aa

    called = {"lookup": False}

    def fake_lookup(*args, **kwargs):
        called["lookup"] = True
        return object()

    monkeypatch.setattr(aa.orthology, "lookup_best_profiled_ortholog", fake_lookup)
    monkeypatch.setattr(
        aa,
        "_resolve_profile_from_catalog",
        lambda profile_id, **kwargs: type(
            "P",
            (),
            {"kegg_organism_code": "mory", "profile_id": profile_id},
        )(),
    )

    decision = aa._decide_ortholog_action(
        allow_ortholog_fallback=True,
        ortholog_override={"profile_id": "mory"},
        cumulative_relevance=aa.pmc.DEFAULT_TARGET_RELEVANCE + 1,
        kegg_code="mtu",
        gene="Rv0001",
        cache_dir="./.cache",
    )
    assert decision.hit is None
    assert decision.skipped_reason == "target_relevance_sufficient"
    assert called["lookup"] is False
