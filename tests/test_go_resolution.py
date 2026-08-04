import logging
from types import SimpleNamespace

from autoannotation import go_resolution
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

    sentinel_rank_fn = object()
    attachment = resolve_for_annotation(
        function="DNA repair",
        functional_category=["Genome maintenance"],
        ranker_models=["model"],
        embedder=injected_embedder,
        resolve_fn=fake_resolve,
        rank_fn=sentinel_rank_fn,
    )

    assert calls == [
        {
            "function": "DNA repair",
            "functional_category": ["Genome maintenance"],
            "ontology_path": "/configured/go-basic.obo",
            "embedder": injected_embedder,
            "ranker_models": ["model"],
            "rank_fn": sentinel_rank_fn,
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


def test_resolve_defaults_to_router_backed_rank_fn(monkeypatch, tmp_path):
    obo_path = tmp_path / "go-basic.obo"
    obo_path.write_text("[Term]\nid: GO:0000001\nname: placeholder\n")
    calls = []

    def fake_resolve(**kwargs):
        calls.append(kwargs)
        return GoResolutionResult(
            go_terms=(), method="no_candidates", queries=(), shortlist=(), votes=(),
        )

    resolve_for_annotation(
        function="DNA repair",
        functional_category=None,
        ranker_models=["model"],
        ontology_path=str(obo_path),
        embedder=object(),
        resolve_fn=fake_resolve,
    )

    assert calls[0]["rank_fn"] is go_resolution._router_rank_fn


def test_resolve_missing_ontology_file_returns_error_not_no_candidates(tmp_path, caplog):
    missing_path = tmp_path / "does-not-exist.obo"

    with caplog.at_level(logging.WARNING, logger=go_resolution.__name__):
        attachment = resolve_for_annotation(
            function="DNA repair",
            functional_category=None,
            ranker_models=["model"],
            ontology_path=str(missing_path),
        )

    assert attachment.go_terms == []
    assert attachment.resolution["method"] == "error"
    assert attachment.resolution["method"] != "no_candidates"
    assert str(missing_path) in attachment.resolution["error"]
    assert any(
        str(missing_path) in record.message for record in caplog.records
    )


def test_resolve_empty_ontology_file_returns_error(tmp_path):
    empty_path = tmp_path / "empty.obo"
    empty_path.write_text("")

    attachment = resolve_for_annotation(
        function="DNA repair",
        functional_category=None,
        ranker_models=["model"],
        ontology_path=str(empty_path),
    )

    assert attachment.go_terms == []
    assert attachment.resolution["method"] == "error"
    assert "empty" in attachment.resolution["error"].lower()


def test_resolve_missing_ontology_does_not_call_injected_resolver(tmp_path):
    """A caller-supplied resolve_fn owns its own ontology handling and must
    still run even if the default OBO path env var points nowhere."""
    missing_path = tmp_path / "does-not-exist.obo"
    calls = []

    def fake_resolve(**kwargs):
        calls.append(kwargs)
        return GoResolutionResult(
            go_terms=(), method="exact_only", queries=(), shortlist=(), votes=(),
        )

    attachment = resolve_for_annotation(
        function="DNA repair",
        functional_category=None,
        ranker_models=["model"],
        ontology_path=str(missing_path),
        embedder=object(),
        resolve_fn=fake_resolve,
    )

    assert len(calls) == 1
    assert attachment.resolution["method"] == "exact_only"


def test_resolve_soft_fail_logs_warning_with_exc_info(caplog):
    def boom(**kwargs):
        raise RuntimeError("ollama down")

    with caplog.at_level(logging.WARNING, logger=go_resolution.__name__):
        resolve_for_annotation(
            function="DNA repair",
            functional_category=None,
            ranker_models=["model"],
            embedder=object(),
            resolve_fn=boom,
        )

    warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warning_records) == 1
    assert "ollama down" in warning_records[0].message
    assert warning_records[0].exc_info is not None


def test_resolve_soft_fail_uses_exception_class_name_when_message_empty(caplog):
    class BlankError(Exception):
        pass

    def boom(**kwargs):
        raise BlankError()

    with caplog.at_level(logging.WARNING, logger=go_resolution.__name__):
        attachment = resolve_for_annotation(
            function="DNA repair",
            functional_category=None,
            ranker_models=["model"],
            embedder=object(),
            resolve_fn=boom,
        )

    assert attachment.resolution["error"] == "BlankError"
    warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warning_records) == 1
    assert "BlankError" in warning_records[0].message
    assert warning_records[0].exc_info is not None
