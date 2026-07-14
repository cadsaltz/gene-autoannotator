"""Regression: UI-saved profile fields must reach the annotation worker."""

from autoannotation import autoannotation as annotation_pipeline
from autoannotation import field_defs
from autoannotation import metadata
from autoannotation import organisms
from autoannotation import orthology
from coordinator.api import create_app
from coordinator.job_store import JobStore
from coordinator.profile_store import LocalProfileStore
from fastapi.testclient import TestClient


def test_profile_lookup_uses_builtin_source_override():
    config = {
        "profile_id": "mtb-h37rv",
        "canonical_name": "Mycobacterium tuberculosis H37Rv",
        "species_name": "Mycobacterium tuberculosis",
        "strain": "H37Rv",
        "synonyms": ["mtb-h37rv"],
        "species_synonyms": [],
        "strain_synonyms": [],
        "locus_regex": r"^Rv\d{4}[Ac]?$",
        "search_terms": ["Mycobacterium tuberculosis"],
        "target_patterns": [],
        "off_target_patterns": [],
        "excluded_species_patterns": [],
        "kegg_organism_code": "mtu",
        "custom_fields": [
            {
                "key": "drug_susc_impact",
                "label": "Drug susceptibility impact",
                "description": "Impact",
                "type": "string",
                "required": False,
                "inference_strategy": "paper_llm",
                "ortholog_allowed": True,
            }
        ],
        "default_field_ortholog": {
            "function": True,
            "functional_category": True,
        },
    }
    lookup = annotation_pipeline._profile_lookup_from_config(config)
    assert lookup is not None
    assert lookup("mtb-h37rv")["default_field_ortholog"]["functional_category"] is True


def test_job_submission_stores_kegg_and_field_ortholog_for_builtin_override(tmp_path):
    profile_store = LocalProfileStore(tmp_path / "profiles")
    builtin = profile_store.get_profile("mtb-h37rv")
    payload = {
        **builtin,
        "default_field_ortholog": {
            "function": True,
            "functional_category": True,
        },
        "custom_fields": [
            {**field, "ortholog_allowed": True}
            for field in builtin["custom_fields"]
        ],
    }
    for key in ("created_at", "updated_at", "source", "trusted", "read_only"):
        payload.pop(key, None)
    profile_store.update_user_profile("mtb-h37rv", payload)

    job_store = JobStore(tmp_path / "jobs.sqlite3")
    app = create_app(
        job_store=job_store,
        profile_store=profile_store,
        run_job=lambda request: {"annotation": {"gene_id": request.locus}},
        run_jobs_inline=False,
        start_worker=False,
    )
    client = TestClient(app)
    created = client.post(
        "/jobs",
        json={
            "profile": "mtb-h37rv",
            "locus": "Rv1734c",
            "allow_ortholog_fallback": True,
        },
    ).json()
    stored = job_store.get_job(created["job_id"])
    config = stored["request"]["profile_config"]

    assert config["kegg_organism_code"] == "mtu"
    assert config["default_field_ortholog"]["function"] is True
    assert config["default_field_ortholog"]["functional_category"] is True
    assert all(field["ortholog_allowed"] for field in config["custom_fields"])
    assert stored["request"]["ortholog_profile_catalog"]
    assert any(
        item["kegg_organism_code"] == "mtu"
        for item in stored["request"]["ortholog_profile_catalog"]
    )

    # Annotation path should honor the override, not code defaults.
    profile = organisms.profile_from_mapping(config)
    defs = field_defs.resolve_effective_fields(profile)
    eligible = metadata.fields_eligible_for_ortholog(defs)
    assert "function" in eligible
    assert "functional_category" in eligible
    assert "drug_susc_impact" in eligible


def test_extra_profiles_make_ssdb_hits_selectable():
    hit = orthology.OrthologHit(
        source_organism_code="cgb",
        source_organism_name="Corynebacterium glutamicum",
        source_gene_id="NCgl0001",
        source_gene_name="dnaA",
        score=200.0,
        identity=0.55,
        lookup_source="kegg_ssdb",
    )
    assert orthology.supports_ortholog_literature_pass(hit) is False
    catalog = [{
        "profile_id": "cglutamicum-atcc13032",
        "canonical_name": "Corynebacterium glutamicum ATCC 13032",
        "species_name": "Corynebacterium glutamicum",
        "kegg_organism_code": "cgb",
        "locus_regex": r"^NCgl\d+$",
        "search_terms": ["Corynebacterium glutamicum"],
        "target_patterns": [r"Corynebacterium\s+glutamicum"],
        "custom_fields": [],
        "default_field_ortholog": {},
    }]
    assert orthology.supports_ortholog_literature_pass(hit, extra_profiles=catalog) is True
    selected = orthology.select_best_profiled_ortholog([hit], extra_profiles=catalog)
    assert selected.source_gene_id == "NCgl0001"


def test_mmi_marinum_hint_is_supported():
    hit = orthology.OrthologHit(
        source_organism_code="mmi",
        source_organism_name="Mycobacterium marinum",
        source_gene_id="MMAR_3491",
        source_gene_name="pyruvate dehydrogenase (E2 component)",
        score=360.0,
        identity=0.736,
        lookup_source="kegg_ssdb",
    )
    assert orthology.supports_ortholog_literature_pass(hit) is True
