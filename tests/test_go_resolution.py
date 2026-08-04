from types import SimpleNamespace

from autoannotation.go_resolution import (
    is_go_resolution_enabled,
    resolve_for_annotation,
)
from goresolve.types import GoCandidate, GoResolutionResult, ResolvedGoTerm


def test_is_go_resolution_enabled_uses_profile_opt_in():
    assert is_go_resolution_enabled(SimpleNamespace(go_resolution_enabled=True)) is True
    assert is_go_resolution_enabled(SimpleNamespace(go_resolution_enabled=False)) is False
    assert is_go_resolution_enabled(SimpleNamespace()) is False
    assert is_go_resolution_enabled(None) is False


def test_resolve_skipped_no_text_does_not_call_resolver():
    def unexpected_resolve(**kwargs):
        raise AssertionError("resolver should not be called")

    attachment = resolve_for_annotation(
        function=None,
        functional_category=None,
        ranker_models=["model"],
        resolve_fn=unexpected_resolve,
    )

    assert attachment.go_terms == []
    assert attachment.resolution == {
        "method": "skipped_no_text",
        "queries": [],
        "shortlist_size": 0,
    }


def test_resolve_soft_fails_on_exception():
    def boom(**kwargs):
        raise RuntimeError("ollama down")

    attachment = resolve_for_annotation(
        function="DNA repair",
        functional_category=None,
        ranker_models=["model"],
        embedder=object(),
        resolve_fn=boom,
    )

    assert attachment.go_terms == []
    assert attachment.resolution["method"] == "error"
    assert "ollama down" in attachment.resolution["error"]


def test_resolve_soft_fails_on_invalid_inputs():
    attachment = resolve_for_annotation(
        function=None,
        functional_category=1,
        ranker_models=["model"],
    )

    assert attachment.go_terms == []
    assert attachment.resolution["method"] == "error"
    assert attachment.resolution["error"]


def test_resolve_serializes_terms_without_agreement_or_full_ranking_metadata(monkeypatch):
    monkeypatch.setenv("GO_BASIC_OBO_PATH", "/configured/go-basic.obo")
    candidate = GoCandidate(
        id="GO:0006281",
        name="DNA repair",
        aspect="biological_process",
        definition="Repair of damaged DNA.",
        score=0.98,
        source="exact",
    )
    result = GoResolutionResult(
        go_terms=(
            ResolvedGoTerm(
                id=candidate.id,
                name=candidate.name,
                aspect=candidate.aspect,
                confidence=1.0,
                method="exact_label",
                sources=("DNA repair",),
                agreement=None,
            ),
        ),
        method="exact_only",
        queries=("DNA repair",),
        shortlist=(candidate,),
        votes=({"model": "model", "ids": [candidate.id]},),
    )
    calls = []
    injected_embedder = object()

    def fake_resolve(**kwargs):
        calls.append(kwargs)
        return result

    attachment = resolve_for_annotation(
        function="DNA repair",
        functional_category=["Genome maintenance"],
        ranker_models=["model"],
        embedder=injected_embedder,
        resolve_fn=fake_resolve,
    )

    assert calls == [
        {
            "function": "DNA repair",
            "functional_category": ["Genome maintenance"],
            "ontology_path": "/configured/go-basic.obo",
            "embedder": injected_embedder,
            "ranker_models": ["model"],
        }
    ]
    assert attachment.go_terms == [
        {
            "id": "GO:0006281",
            "name": "DNA repair",
            "aspect": "biological_process",
            "method": "exact_label",
            "confidence": 1.0,
        }
    ]
    assert attachment.resolution == {
        "method": "exact_only",
        "queries": ["DNA repair"],
        "shortlist_size": 1,
    }
    assert "shortlist" not in attachment.resolution
    assert "votes" not in attachment.resolution
