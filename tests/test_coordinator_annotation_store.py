import hashlib
import re

from backend.annotation_store import InMemoryAnnotationStore


def name_only_job(job_id, gene_name, generated_at="2026-01-01T00:00:00Z"):
    return {
        "id": job_id,
        "request": {"organism": "Custom bacterium", "name": gene_name},
        "result": {
            "annotation": {
                "gene_id": None,
                "name": gene_name,
                "annotation_metadata": {
                    "generated_at": generated_at,
                    "profile_id": "ad-hoc-custom-bacterium",
                    "canonical_name": "Custom bacterium",
                    "species_name": "Custom bacterium",
                    "strain": None,
                    "resolved_locus": None,
                    "resolved_name": gene_name,
                    "profile_source": "ad_hoc",
                },
            }
        },
        "finished_at": generated_at,
    }


def expected_name_identity(gene_name):
    digest = hashlib.sha256(gene_name.strip().casefold().encode("utf-8")).hexdigest()[:10]
    return f"ad-hoc-custom-bacterium:name:abc1-{digest}"


def test_annotation_store_versions_current_annotation_by_profile_and_locus():
    store = InMemoryAnnotationStore()
    first_job = {
        "id": "first-job",
        "request": {"profile": "mtb-h37rv", "locus": "Rv0001", "name": "dnaA"},
        "result": {
            "annotation": {
                "gene_id": "Rv0001",
                "name": "dnaA",
                "annotation_metadata": {"generated_at": "2026-01-01T00:00:00Z"},
            },
            "output_path": "gen_json/gen_Rv0001.json",
        },
        "output_path": "gen_json/gen_Rv0001.json",
        "finished_at": "2026-01-01T00:00:00Z",
    }
    second_job = {
        "id": "second-job",
        "request": {"organism": "M. tuberculosis", "strain": "H37Rv", "locus": "Rv0001"},
        "result": {
            "annotation": {
                "gene_id": "Rv0001",
                "name": "dnaA updated",
                "annotation_metadata": {"generated_at": "2026-02-01T00:00:00Z"},
            },
            "output_path": "gen_json/gen_Rv0001_v2.json",
        },
        "output_path": "gen_json/gen_Rv0001_v2.json",
        "finished_at": "2026-02-01T00:00:00Z",
    }

    annotation_id = store.save_completed_job(first_job)
    updated_id = store.save_completed_job(second_job)
    detail = store.get(annotation_id)
    versions = store.get_versions(annotation_id)
    matches = store.search("dnaA updated")

    assert annotation_id == "mtb-h37rv:Rv0001"
    assert updated_id == annotation_id
    assert detail["gene_name"] == "dnaA updated"
    assert detail["generated_at"] == "2026-02-01T00:00:00Z"
    assert detail["version_count"] == 1
    assert versions[0]["job_id"] == "first-job"
    assert versions[0]["gene_name"] == "dnaA"
    assert matches[0]["id"] == annotation_id


def test_annotation_store_search_returns_empty_list_for_miss():
    store = InMemoryAnnotationStore()

    assert store.search("missing") == []


def test_annotation_store_supports_name_only_identity():
    store = InMemoryAnnotationStore()
    job = name_only_job("name-only-job", "abc1")

    annotation_id = store.save_completed_job(job)

    assert annotation_id == expected_name_identity("abc1")
    assert store.get(annotation_id)["normalized_locus"] is None


def test_name_only_annotation_id_is_stable_readable_and_hashed():
    store = InMemoryAnnotationStore()

    first_id = store.save_completed_job(name_only_job("first-job", "abc1"))
    second_id = store.save_completed_job(name_only_job("second-job", "abc1"))

    assert first_id == second_id
    assert re.fullmatch(r"ad-hoc-custom-bacterium:name:abc1-[0-9a-f]{10}", first_id)
    assert first_id == expected_name_identity("abc1")


def test_name_only_annotation_id_uses_non_empty_slug_fallback():
    store = InMemoryAnnotationStore()

    annotation_id = store.save_completed_job(name_only_job("symbol-job", "!!!"))

    assert re.fullmatch(r"ad-hoc-custom-bacterium:name:gene-[0-9a-f]{10}", annotation_id)


def test_repeated_name_only_jobs_version_together():
    store = InMemoryAnnotationStore()

    first_id = store.save_completed_job(
        name_only_job("first-name-job", "abc1", "2026-01-01T00:00:00Z")
    )
    second_id = store.save_completed_job(
        name_only_job("second-name-job", "abc1", "2026-02-01T00:00:00Z")
    )
    detail = store.get(first_id)
    versions = store.get_versions(first_id)

    assert second_id == first_id
    assert detail["generated_at"] == "2026-02-01T00:00:00Z"
    assert detail["version_count"] == 1
    assert versions[0]["job_id"] == "first-name-job"


def test_distinct_name_only_targets_with_same_normalized_slug_do_not_merge():
    store = InMemoryAnnotationStore()

    hyphen_id = store.save_completed_job(name_only_job("hyphen-job", "abc-1"))
    underscore_id = store.save_completed_job(name_only_job("underscore-job", "abc_1"))

    assert hyphen_id != underscore_id
    assert store.get(hyphen_id)["version_count"] == 0
    assert store.get(underscore_id)["version_count"] == 0
