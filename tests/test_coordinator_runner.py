from coordinator.runner import run_annotation_job
from coordinator.schemas import AnnotationJobRequest


def test_runner_calls_existing_cli_main():
    captured = {}

    def fake_main(**kwargs):
        captured.update(kwargs)
        return {
            "annotation": {"gene_id": "TcCLB.503799.4"},
            "papers_used": ["1"],
            "all_papers": ["1"],
            "output_path": "gen_json/tcruzi-clbrener/gen_TcCLB.503799.4.json",
            "cumulative_relevance": 1.0,
            "selection_mode": "all_eligible_limited_literature",
        }

    request = AnnotationJobRequest(
        profile="tcruzi-clbrener",
        locus="TcCLB.503799.4",
        name="TcUBP1",
        allow_online_name_lookup=False,
        cache_supplied_name=True,
    )

    result = run_annotation_job(request, annotation_main=fake_main)

    assert captured == {
        "gene": None,
        "profile": "tcruzi-clbrener",
        "profile_config": None,
        "organism": None,
        "strain": None,
        "locus": "TcCLB.503799.4",
        "name": "TcUBP1",
        "cache_dir": "./.cache",
        "output_dir": "gen_json",
        "gene_name_cache": ".cache/gene_names",
        "no_online_name_lookup": True,
        "refresh_gene_name_cache": False,
        "cache_supplied_name": True,
        "allow_ortholog_fallback": False,
        "ortholog_override": None,
        "ortholog_catalog": [],
    }
    assert result["annotation"]["gene_id"] == "TcCLB.503799.4"
    assert result["output_path"].endswith("gen_TcCLB.503799.4.json")


def test_runner_passes_name_only_request_to_cli_main():
    captured = {}

    def fake_main(**kwargs):
        captured.update(kwargs)
        return {"annotation": {"gene_id": None, "name": "abc1"}}

    request = AnnotationJobRequest(organism="Custom bacterium", name="abc1")

    run_annotation_job(request, annotation_main=fake_main)

    assert captured["locus"] is None
    assert captured["name"] == "abc1"
    assert captured["organism"] == "Custom bacterium"


def test_runner_passes_profile_config_to_cli_main():
    captured = {}
    profile_config = {
        "profile_id": "custom-profile",
        "canonical_name": "Custom organism",
        "species_name": "Custom organism",
        "strain": "Lab strain",
        "synonyms": ["custom-profile"],
        "species_synonyms": ["Custom organism"],
        "strain_synonyms": ["Lab strain"],
        "locus_regex": r"^CUS_\d+$",
        "search_terms": ["Custom organism"],
        "target_patterns": [r"Custom\s+organism"],
        "off_target_patterns": [],
        "excluded_species_patterns": [],
    }

    def fake_main(**kwargs):
        captured.update(kwargs)
        return {"annotation": {"gene_id": "CUS_0001"}}

    request = AnnotationJobRequest(
        profile="custom-profile",
        locus="CUS_0001",
        profile_config=profile_config,
        allow_online_name_lookup=False,
    )

    run_annotation_job(request, annotation_main=fake_main)

    assert captured["profile"] == "custom-profile"
    assert captured["profile_config"] == profile_config


def test_runner_forwards_ortholog_fields():
    from coordinator.runner import run_annotation_job
    from coordinator.schemas import AnnotationJobRequest

    captured = {}

    def fake_main(**kwargs):
        captured.update(kwargs)
        return {"ok": True}

    request = AnnotationJobRequest(
        profile="mtb-h37rv", locus="Rv0001",
        allow_ortholog_fallback=True,
        ortholog_override={"profile_id": "mtb-h37rv", "locus": "Rv9999", "name": "x"},
    )
    run_annotation_job(request, annotation_main=fake_main)

    assert captured["allow_ortholog_fallback"] is True
    assert captured["ortholog_override"] == {"profile_id": "mtb-h37rv", "locus": "Rv9999", "name": "x"}
    assert captured["ortholog_catalog"] == []
