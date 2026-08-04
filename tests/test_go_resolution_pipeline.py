import dataclasses
import json

import pandas as pd
import pytest

from autoannotation import autoannotation
from autoannotation import organisms
from autoannotation.go_resolution import GoResolutionAttachment
from autoannotation.orthology import OrthologHit
from autoannotation.pmc import PaperSelectionResult, RelevanceRecord


TARGET_JSON = json.dumps({
    "gene_id": "Rv0001",
    "name": "dnaA",
    "function": "Initiates chromosomal DNA replication.",
    "functional_category": ["DNA replication"],
    "drug_susc_impact": "",
    "infection_impact": "",
    "essential_in_vitro": True,
    "essential_in_vivo": True,
    "annotation_notes": "Direct pass notes.",
})

ORTHOLOG_JSON = json.dumps({
    "gene_id": "MO_000001",
    "name": "dnaA",
    "function": "Initiates DNA replication in M. orygis.",
    "functional_category": ["DNA replication", "Ortholog category"],
    "drug_susc_impact": None,
    "infection_impact": None,
    "essential_in_vitro": None,
    "essential_in_vivo": None,
    "annotation_notes": "Ortholog pass notes.",
})


class FakeLlmHandler:
    def __init__(self, cache_dir):
        self.cache_dir = cache_dir
        self.aggregate_calls = 0

    @staticmethod
    def json_regex_filter(gene_json, organism_profile=None, expected_gene=None, relaxed_name=False):
        return True

    def get_llm_gene_info_json(
        self, gene_id, gene_name, info_text, model, section_type='abstract',
        organism_profile=None, evidence_mode='target', ortholog_context=None,
        field_defs_profile=None,
    ):
        if evidence_mode == 'ortholog':
            return ORTHOLOG_JSON, 0.1
        return TARGET_JSON, 0.1

    def get_llm_consensus_json(
        self, candidates, *, excerpt=None, expected_gene_id=None, expected_name=None,
        model, section_type='abstract', organism_profile=None,
        allow_missing_locus=False, field_defs_profile=None,
    ):
        return candidates[0], 0.1

    def get_llm_aggregate_json(
        self, json_responses, pmids, model, literature_context=None, relevance_scores=None,
        organism_profile=None, allow_missing_locus=False,
        evidence_mode='target', ortholog_context=None, field_defs_profile=None,
    ):
        self.aggregate_calls += 1
        if evidence_mode == 'ortholog':
            return ORTHOLOG_JSON, 0.1
        return TARGET_JSON, 0.1

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
        pmc_id = "99" if gene == "MO_000001" else "1"
        return [
            RelevanceRecord(
                pmc_id=pmc_id,
                pmid="99999" if pmc_id == "99" else "12345",
                score=0.8,
                retrieval_sources=["locus"],
                title="dnaA paper",
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
        return "dnaA is discussed in this paper."

    def get_results(self, pmc_id):
        return None

    def get_discussion(self, pmc_id):
        return None

    def get_pmid(self, pmc_id):
        return {"1": "12345", "99": "99999"}.get(pmc_id, "12345")


_ORIGINAL_RESOLVE_PROFILE = organisms.resolve_profile


def _enabled_profile():
    base = _ORIGINAL_RESOLVE_PROFILE('mtb-h37rv')
    return dataclasses.replace(base, go_resolution_enabled=True)


def _patch_common(monkeypatch, *, enabled):
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
    if enabled:
        monkeypatch.setattr(
            autoannotation.organisms, "resolve_profile", lambda *a, **k: _enabled_profile()
        )


def _fake_ortholog_hit():
    return OrthologHit(
        source_organism_code='mory',
        source_organism_name='Mycobacterium orygis',
        source_gene_id='MO_000001',
        source_gene_name='dnaA',
        score=507.0,
        identity=0.82,
        lookup_source='kegg_ssdb',
    )


def _canned_attachment(tag):
    return GoResolutionAttachment(
        go_terms=[{"id": f"GO:{tag}", "name": f"term {tag}", "aspect": "biological_process"}],
        resolution={"method": "ranked", "queries": [tag], "shortlist_size": 1},
    )


def test_go_resolution_never_called_when_disabled(monkeypatch, tmp_path):
    _patch_common(monkeypatch, enabled=False)
    calls = []

    def fake_resolve(**kwargs):
        calls.append(kwargs)
        return _canned_attachment("should-not-happen")

    monkeypatch.setattr(autoannotation.go_resolution, "resolve_for_annotation", fake_resolve)

    result = autoannotation.get_gene_annotation("Rv0001", cache_dir=tmp_path)

    assert calls == []
    assert "go_terms" not in result["gene_annotation"]
    assert "go_resolution" not in result["gene_annotation"]["annotation_metadata"]


def test_go_resolution_called_once_for_target_only_pass(monkeypatch, tmp_path):
    _patch_common(monkeypatch, enabled=True)
    calls = []

    def fake_resolve(**kwargs):
        calls.append(kwargs)
        return _canned_attachment("target")

    monkeypatch.setattr(autoannotation.go_resolution, "resolve_for_annotation", fake_resolve)

    result = autoannotation.get_gene_annotation("Rv0001", cache_dir=tmp_path)

    assert len(calls) == 1
    assert calls[0]["function"] == "Initiates chromosomal DNA replication."
    assert calls[0]["functional_category"] == ["DNA replication"]
    assert calls[0]["ranker_models"] == list(autoannotation.MODEL_SUMMARY)

    annotation = result["gene_annotation"]
    assert annotation["go_terms"] == _canned_attachment("target").go_terms
    assert annotation["annotation_metadata"]["go_resolution"] == (
        _canned_attachment("target").resolution
    )
    assert "ortholog_go_terms" not in annotation["annotation_metadata"]


def test_go_resolution_called_for_ortholog_pass_with_ortholog_text(monkeypatch, tmp_path):
    _patch_common(monkeypatch, enabled=True)
    monkeypatch.setattr(
        autoannotation.orthology, "lookup_best_profiled_ortholog",
        lambda *args, **kwargs: _fake_ortholog_hit(),
    )
    calls = []

    def fake_resolve(**kwargs):
        calls.append(kwargs)
        tag = "ortholog" if kwargs["function"] and "orygis" in kwargs["function"] else "target"
        return _canned_attachment(tag)

    monkeypatch.setattr(autoannotation.go_resolution, "resolve_for_annotation", fake_resolve)

    result = autoannotation.get_gene_annotation(
        "Rv0001", cache_dir=tmp_path, allow_ortholog_fallback=True,
    )

    assert len(calls) == 2
    assert calls[0]["function"] == "Initiates chromosomal DNA replication."
    assert calls[0]["functional_category"] == ["DNA replication"]
    assert calls[1]["function"] == "Initiates DNA replication in M. orygis."
    assert calls[1]["functional_category"] == ["DNA replication", "Ortholog category"]

    annotation = result["gene_annotation"]
    # Target go_terms must remain the target-derived attachment, unaffected by
    # the ortholog merge.
    assert annotation["go_terms"] == _canned_attachment("target").go_terms
    assert annotation["annotation_metadata"]["go_resolution"] == (
        _canned_attachment("target").resolution
    )
    assert annotation["annotation_metadata"]["ortholog_go_terms"] == (
        _canned_attachment("ortholog").go_terms
    )
    assert annotation["annotation_metadata"]["ortholog_go_resolution"] == (
        _canned_attachment("ortholog").resolution
    )


def test_go_resolution_progress_phases_emitted_when_enabled(monkeypatch, tmp_path):
    from shared.job_progress import JobProgressEvent

    _patch_common(monkeypatch, enabled=True)
    monkeypatch.setattr(
        autoannotation.orthology, "lookup_best_profiled_ortholog",
        lambda *args, **kwargs: _fake_ortholog_hit(),
    )
    monkeypatch.setattr(
        autoannotation.go_resolution, "resolve_for_annotation",
        lambda **kwargs: _canned_attachment("x"),
    )

    events: list[JobProgressEvent] = []
    autoannotation.get_gene_annotation(
        "Rv0001", cache_dir=tmp_path, allow_ortholog_fallback=True,
        progress_cb=events.append,
    )

    phases = [event.phase for event in events]
    assert "go_resolving" in phases
    assert "ortholog_go_resolving" in phases


def test_go_resolution_skipped_when_disabled_even_with_ortholog(monkeypatch, tmp_path):
    _patch_common(monkeypatch, enabled=False)
    monkeypatch.setattr(
        autoannotation.orthology, "lookup_best_profiled_ortholog",
        lambda *args, **kwargs: _fake_ortholog_hit(),
    )
    calls = []

    def fake_resolve(**kwargs):
        calls.append(kwargs)
        return _canned_attachment("should-not-happen")

    monkeypatch.setattr(autoannotation.go_resolution, "resolve_for_annotation", fake_resolve)

    result = autoannotation.get_gene_annotation(
        "Rv0001", cache_dir=tmp_path, allow_ortholog_fallback=True,
    )

    assert calls == []
    annotation = result["gene_annotation"]
    assert "go_terms" not in annotation
    assert "ortholog_go_terms" not in annotation["annotation_metadata"]
