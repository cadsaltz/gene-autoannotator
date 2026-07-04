import time

import pytest
from fastapi.testclient import TestClient

from coordinator.annotation_store import InMemoryAnnotationStore
from coordinator.api import create_app
from coordinator.job_store import JobStore
from coordinator.profile_store import BuiltinAndUserProfileStore, InMemoryUserProfileStore
from coordinator import regex_gen


class FailingProfileStore:
    def health(self):
        return {"status": "unavailable", "message": "mongo down"}

    def list_profiles(self):
        raise RuntimeError("mongo down")

    def get_profile(self, profile_id):
        raise RuntimeError("mongo down")


@pytest.fixture(autouse=True)
def clear_mongo_env(monkeypatch):
    monkeypatch.delenv("MONGO_URI", raising=False)
    monkeypatch.delenv("MONGODB_URI", raising=False)


def test_health_endpoint(tmp_path):
    app = create_app(job_store=JobStore(tmp_path / "jobs.sqlite3"))
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["stores"]["jobs"]["status"] == "ok"
    assert payload["stores"]["profiles"]["status"] == "ok"
    assert "queue" in payload
    assert payload["resources"]["status"] == "ok"
    assert "cpu_percent" in payload["resources"]
    assert "memory_total_bytes" in payload["resources"]
    assert "memory_used_bytes" in payload["resources"]
    assert "memory_available_bytes" in payload["resources"]
    assert "memory_percent" in payload["resources"]


def test_cors_allows_local_frontend_origin(tmp_path):
    app = create_app(job_store=JobStore(tmp_path / "jobs.sqlite3"))
    client = TestClient(app)

    response = client.options(
        "/health",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_cors_allows_private_network_frontend_origin(tmp_path):
    app = create_app(job_store=JobStore(tmp_path / "jobs.sqlite3"))
    client = TestClient(app)

    response = client.options(
        "/validate",
        headers={
            "Origin": "http://10.158.45.197:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://10.158.45.197:3000"


def test_profiles_endpoint_lists_configured_profiles(tmp_path):
    app = create_app(job_store=JobStore(tmp_path / "jobs.sqlite3"))
    client = TestClient(app)

    response = client.get("/profiles")

    assert response.status_code == 200
    profile_ids = {profile["profile_id"] for profile in response.json()["profiles"]}
    assert "mtb-h37rv" in profile_ids
    assert "tcruzi-clbrener" in profile_ids


def test_profiles_endpoint_includes_user_profiles(tmp_path):
    profile_store = BuiltinAndUserProfileStore(user_store=InMemoryUserProfileStore())
    profile_store.create_user_profile({
        "profile_id": "custom-profile",
        "canonical_name": "Custom organism",
        "species_name": "Custom organism",
        "locus_regex": r"^CUS_\d+$",
    })
    app = create_app(
        job_store=JobStore(tmp_path / "jobs.sqlite3"),
        profile_store=profile_store,
    )
    client = TestClient(app)

    response = client.get("/profiles")

    assert response.status_code == 200
    profiles = {profile["profile_id"]: profile for profile in response.json()["profiles"]}
    assert profiles["mtb-h37rv"]["source"] == "builtin"
    assert profiles["custom-profile"]["source"] == "user"


def test_profiles_endpoint_reports_store_failures_as_unavailable(tmp_path):
    app = create_app(
        job_store=JobStore(tmp_path / "jobs.sqlite3"),
        profile_store=FailingProfileStore(),
    )
    client = TestClient(app)

    response = client.get("/profiles")

    assert response.status_code == 503
    assert response.json()["detail"] == "mongo down"


def test_profile_detail_endpoint_reports_store_failures_as_unavailable(tmp_path):
    app = create_app(
        job_store=JobStore(tmp_path / "jobs.sqlite3"),
        profile_store=FailingProfileStore(),
    )
    client = TestClient(app)

    response = client.get("/profiles/custom-profile")

    assert response.status_code == 503
    assert response.json()["detail"] == "mongo down"


def test_profile_crud_allows_builtin_update(tmp_path):
    app = create_app(
        job_store=JobStore(tmp_path / "jobs.sqlite3"),
        profile_store=BuiltinAndUserProfileStore(user_store=InMemoryUserProfileStore()),
    )
    client = TestClient(app)

    response = client.put(
        "/profiles/mtb-h37rv",
        json={
            "profile_id": "mtb-h37rv",
            "canonical_name": "Mycobacterium tuberculosis H37Rv edited",
            "species_name": "Mycobacterium tuberculosis",
            "locus_regex": r"^Rv\d{4}[Ac]?$",
        },
    )

    assert response.status_code == 200
    assert response.json()["canonical_name"] == "Mycobacterium tuberculosis H37Rv edited"
    assert response.json()["source"] == "builtin"


def test_profile_creation_without_user_store_returns_unavailable(tmp_path):
    app = create_app(job_store=JobStore(tmp_path / "jobs.sqlite3"))
    client = TestClient(app)

    response = client.post(
        "/profiles",
        json={
            "profile_id": "custom-profile",
            "canonical_name": "Custom organism",
            "species_name": "Custom organism",
        },
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "MONGO_URI is not configured"


def test_profile_crud_creates_reads_updates_and_deletes_user_profile(tmp_path):
    app = create_app(
        job_store=JobStore(tmp_path / "jobs.sqlite3"),
        profile_store=BuiltinAndUserProfileStore(user_store=InMemoryUserProfileStore()),
    )
    client = TestClient(app)

    create_response = client.post(
        "/profiles",
        json={
            "profile_id": "custom-profile",
            "canonical_name": "Custom organism",
            "species_name": "Custom organism",
            "strain": "Lab strain",
            "locus_regex": r"^CUS_\d+$",
            "search_terms": ["Custom organism"],
        },
    )
    read_response = client.get("/profiles/custom-profile")
    update_response = client.put(
        "/profiles/custom-profile",
        json={
            "profile_id": "custom-profile",
            "canonical_name": "Custom organism edited",
            "species_name": "Custom organism",
        },
    )
    delete_response = client.delete("/profiles/custom-profile")
    missing_response = client.get("/profiles/custom-profile")

    assert create_response.status_code == 201
    assert read_response.status_code == 200
    assert read_response.json()["canonical_name"] == "Custom organism"
    assert update_response.status_code == 200
    assert update_response.json()["canonical_name"] == "Custom organism edited"
    assert delete_response.status_code == 200
    assert delete_response.json() == {"deleted": True}
    assert missing_response.status_code == 404


def test_validate_endpoint_wraps_existing_locus_validation(tmp_path):
    app = create_app(job_store=JobStore(tmp_path / "jobs.sqlite3"))
    client = TestClient(app)

    response = client.post(
        "/validate",
        json={
            "organism": "Trypanosoma cruzi",
            "strain": "CL Brener",
            "locus": "TcCLB.506529.310",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["valid"] is True
    assert payload["profile_id"] == "tcruzi-clbrener"


def test_validate_accepts_name_only_custom_organism(tmp_path):
    app = create_app(
        job_store=JobStore(tmp_path / "jobs.sqlite3"),
        profile_store=BuiltinAndUserProfileStore(user_store=InMemoryUserProfileStore()),
    )
    client = TestClient(app)

    response = client.post(
        "/validate",
        json={"organism": "Custom bacterium", "name": "abc1"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["valid"] is True
    assert payload["primary_identifier"] == "abc1"
    assert {warning["code"] for warning in payload["warnings"]} >= {
        "ad_hoc_profile",
        "missing_locus",
    }


@pytest.mark.parametrize("endpoint", ["/validate", "/jobs"])
def test_target_requests_reject_saved_profile_locus_schema_mismatch(tmp_path, endpoint):
    user_store = InMemoryUserProfileStore()
    user_store.create_profile(
        {
            "profile_id": "ecoli-k12-mg1655",
            "canonical_name": "Escherichia coli K-12 MG1655",
            "species_name": "Escherichia coli",
            "strain": "K-12 MG1655",
            "locus_regex": r"^b\d{4}$",
            "target_patterns": [r"Escherichia\s+coli"],
        }
    )
    app = create_app(
        job_store=JobStore(tmp_path / "jobs.sqlite3"),
        profile_store=BuiltinAndUserProfileStore(user_store=user_store),
        run_jobs_inline=False,
        start_worker=False,
    )
    client = TestClient(app)

    response = client.post(
        endpoint,
        json={"profile": "ecoli-k12-mg1655", "locus": "hello"},
    )

    if endpoint == "/validate":
        assert response.status_code == 200
        payload = response.json()
        assert payload["valid"] is False
        assert {warning["code"] for warning in payload["warnings"]} >= {
            "locus_schema_mismatch"
        }
    else:
        assert response.status_code == 422
        assert response.json()["detail"] == "Locus does not match the profile locus schema."


@pytest.mark.parametrize("endpoint", ["/validate", "/jobs"])
def test_target_requests_reject_whitespace_only_locus_and_name(tmp_path, endpoint):
    app = create_app(
        job_store=JobStore(tmp_path / "jobs.sqlite3"),
        run_jobs_inline=False,
        start_worker=False,
    )
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post(
        endpoint,
        json={"organism": "Custom bacterium", "locus": "   ", "name": "\t"},
    )

    assert response.status_code == 422


@pytest.mark.parametrize("endpoint", ["/validate", "/jobs"])
def test_target_requests_report_unknown_profile_as_not_found(tmp_path, endpoint):
    app = create_app(
        job_store=JobStore(tmp_path / "jobs.sqlite3"),
        run_jobs_inline=False,
        start_worker=False,
    )
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post(
        endpoint,
        json={"profile": "missing-profile", "locus": "CUS_0001"},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Profile not found"


@pytest.mark.parametrize("endpoint", ["/validate", "/jobs"])
def test_target_requests_report_profile_store_failures_as_unavailable(tmp_path, endpoint):
    app = create_app(
        job_store=JobStore(tmp_path / "jobs.sqlite3"),
        profile_store=FailingProfileStore(),
        run_jobs_inline=False,
        start_worker=False,
    )
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post(
        endpoint,
        json={"profile": "custom-profile", "locus": "CUS_0001"},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "mongo down"


def test_job_submission_can_complete_inline_with_injected_runner(tmp_path):
    def fake_runner(request):
        return {
            "annotation": {"gene_id": request.locus, "name": request.name},
            "papers_used": ["1"],
            "all_papers": ["1", "2"],
            "output_path": f"gen_json/tcruzi-clbrener/gen_{request.locus}.json",
            "cumulative_relevance": 0.8,
            "selection_mode": "target_relevance_reached",
        }

    app = create_app(
        job_store=JobStore(tmp_path / "jobs.sqlite3"),
        run_job=fake_runner,
        run_jobs_inline=True,
    )
    client = TestClient(app)

    create_response = client.post(
        "/jobs",
        json={
            "profile": "tcruzi-clbrener",
            "locus": "TcCLB.503799.4",
            "name": "TcUBP1",
            "allow_online_name_lookup": False,
        },
    )
    job_id = create_response.json()["job_id"]
    status_response = client.get(f"/jobs/{job_id}")
    result_response = client.get(f"/jobs/{job_id}/result")

    assert create_response.status_code == 201
    assert create_response.json()["status"] == "completed"
    assert status_response.status_code == 200
    assert status_response.json()["status"] == "completed"
    assert result_response.status_code == 200
    assert result_response.json()["annotation"]["gene_id"] == "TcCLB.503799.4"


def test_job_submission_accepts_name_without_locus(tmp_path):
    app = create_app(
        job_store=JobStore(tmp_path / "jobs.sqlite3"),
        run_job=lambda request: {"annotation": {"gene_id": None, "name": request.name}},
        run_jobs_inline=False,
        start_worker=False,
    )
    client = TestClient(app)

    response = client.post(
        "/jobs",
        json={"organism": "Custom bacterium", "name": "abc1"},
    )

    assert response.status_code == 201
    assert response.json()["status"] == "queued"


def test_job_submission_stores_target_preflight_warnings(tmp_path):
    app = create_app(
        job_store=JobStore(tmp_path / "jobs.sqlite3"),
        run_job=lambda request: {"annotation": {"gene_id": None, "name": request.name}},
        run_jobs_inline=False,
        start_worker=False,
    )
    client = TestClient(app)

    created = client.post(
        "/jobs",
        json={"organism": "Custom bacterium", "name": "abc1"},
    ).json()
    job = client.get(f"/jobs/{created['job_id']}").json()

    assert "target_preflight" in job["request"]
    assert {warning["code"] for warning in job["request"]["target_preflight"]["warnings"]} >= {
        "ad_hoc_profile",
        "missing_locus",
    }


def test_job_submission_executes_inferred_builtin_profile(tmp_path):
    captured_request = {}

    def fake_runner(request):
        captured_request["profile"] = request.profile
        captured_request["organism"] = request.organism
        captured_request["strain"] = request.strain
        return {"annotation": {"gene_id": request.locus}}

    job_store = JobStore(tmp_path / "jobs.sqlite3")
    app = create_app(
        job_store=job_store,
        run_job=fake_runner,
        run_jobs_inline=True,
    )
    client = TestClient(app)

    created = client.post(
        "/jobs",
        json={"organism": "Mycobacterium tuberculosis", "locus": "Rv0001"},
    )
    stored_job = job_store.get_job(created.json()["job_id"])

    assert created.status_code == 201
    assert created.json()["status"] == "completed"
    assert captured_request == {
        "profile": "mtb-h37rv",
        "organism": None,
        "strain": None,
    }
    assert stored_job["request"]["profile"] == "mtb-h37rv"
    assert stored_job["request"]["organism"] is None
    assert stored_job["request"]["strain"] is None
    assert stored_job["request"]["target_preflight"]["profile_id"] == "mtb-h37rv"


def test_job_submission_stores_profile_config_for_user_profile(tmp_path):
    profile_store = BuiltinAndUserProfileStore(user_store=InMemoryUserProfileStore())
    profile_store.create_user_profile({
        "profile_id": "custom-profile",
        "canonical_name": "Custom organism",
        "species_name": "Custom organism",
        "strain": "Lab strain",
        "synonyms": ["custom-profile", "Custom organism Lab strain"],
        "species_synonyms": ["Custom organism"],
        "strain_synonyms": ["Lab strain"],
        "locus_regex": r"^CUS_\d+$",
        "search_terms": ["Custom organism", "Lab strain"],
        "target_patterns": [r"Custom\s+organism"],
        "off_target_patterns": [r"Other\s+organism"],
        "excluded_species_patterns": [r"Excluded\s+organism"],
    })
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
            "profile": "custom-profile",
            "locus": "CUS_0001",
            "name": "abc1",
        },
    ).json()
    stored_job = job_store.get_job(created["job_id"])
    public_job = client.get(f"/jobs/{created['job_id']}").json()
    list_response = client.get("/jobs").json()

    profile_config = stored_job["request"]["profile_config"]
    assert profile_config["profile_id"] == "custom-profile"
    assert profile_config["canonical_name"] == "Custom organism"
    assert profile_config["species_name"] == "Custom organism"
    assert profile_config["strain"] == "Lab strain"
    assert profile_config["synonyms"] == ["custom-profile", "Custom organism Lab strain"]
    assert profile_config["species_synonyms"] == ["Custom organism"]
    assert profile_config["strain_synonyms"] == ["Lab strain"]
    assert profile_config["locus_regex"] == r"^CUS_\d+$"
    assert profile_config["search_terms"] == ["Custom organism", "Lab strain"]
    assert profile_config["target_patterns"] == [r"Custom\s+organism"]
    assert profile_config["off_target_patterns"] == [r"Other\s+organism"]
    assert profile_config["excluded_species_patterns"] == [r"Excluded\s+organism"]
    assert "profile_config" not in public_job["request"]
    assert "target_preflight" in public_job["request"]
    listed_job = next(job for job in list_response["jobs"] if job["id"] == created["job_id"])
    assert "profile_config" not in listed_job["request"]
    assert "target_preflight" in listed_job["request"]


def test_worker_marks_stale_invalid_saved_profile_locus_job_failed(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOANNOTATOR_EMBEDDED_WORKER", "true")
    profile_store = BuiltinAndUserProfileStore(user_store=InMemoryUserProfileStore())
    profile_store.create_user_profile({
        "profile_id": "ecoli-k12-mg1655",
        "canonical_name": "Escherichia coli K-12 MG1655",
        "species_name": "Escherichia coli",
        "strain": "K-12 MG1655",
        "locus_regex": r"^b\d{4}$",
        "target_patterns": [r"Escherichia\s+coli"],
    })
    job_store = JobStore(tmp_path / "jobs.sqlite3")
    queued = job_store.create_job({
        "profile": "ecoli-k12-mg1655",
        "locus": "hello",
        "allow_online_name_lookup": False,
        "refresh_gene_name_cache": False,
        "cache_supplied_name": False,
    })

    def fail_if_called(_request):
        raise AssertionError("invalid locus job should fail before annotation runner")

    app = create_app(
        job_store=job_store,
        profile_store=profile_store,
        run_job=fail_if_called,
        start_worker=True,
    )

    with TestClient(app):
        for _ in range(20):
            job = job_store.get_job(queued["id"])
            if job["status"] != "queued":
                break
            time.sleep(0.05)

    assert job["status"] == "failed"
    assert job["error"] == "Locus does not match the profile locus schema."


def test_job_submission_rejects_missing_name_and_locus(tmp_path):
    app = create_app(job_store=JobStore(tmp_path / "jobs.sqlite3"))
    client = TestClient(app)

    response = client.post("/jobs", json={"organism": "Custom bacterium"})

    assert response.status_code == 422


def test_result_endpoint_rejects_unfinished_jobs(tmp_path):
    app = create_app(
        job_store=JobStore(tmp_path / "jobs.sqlite3"),
        run_job=lambda request: {"annotation": {"gene_id": request.locus}},
        run_jobs_inline=False,
        start_worker=False,
    )
    client = TestClient(app)

    create_response = client.post(
        "/jobs",
        json={"profile": "mtb-h37rv", "locus": "Rv0001"},
    )
    job_id = create_response.json()["job_id"]
    result_response = client.get(f"/jobs/{job_id}/result")

    assert create_response.status_code == 201
    assert create_response.json()["status"] == "queued"
    assert result_response.status_code == 409
    assert result_response.json()["detail"] == "Job is not completed"


def test_startup_worker_drains_existing_queued_jobs(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOANNOTATOR_EMBEDDED_WORKER", "true")
    store = JobStore(tmp_path / "jobs.sqlite3")
    queued = store.create_job({"profile": "mtb-h37rv", "locus": "Rv0001"})
    app = create_app(
        job_store=store,
        run_job=lambda request: {"annotation": {"gene_id": request.locus}},
        start_worker=True,
    )

    with TestClient(app):
        for _ in range(50):
            job = store.get_job(queued["id"])
            if job["status"] == "completed":
                break
            time.sleep(0.02)

    assert store.get_job(queued["id"])["status"] == "completed"


def test_job_submission_rejects_conflicting_profile_and_organism(tmp_path):
    app = create_app(job_store=JobStore(tmp_path / "jobs.sqlite3"))
    client = TestClient(app)

    response = client.post(
        "/jobs",
        json={
            "profile": "mtb-h37rv",
            "organism": "Trypanosoma cruzi",
            "locus": "Rv0001",
        },
    )

    assert response.status_code == 422


def test_job_submission_rejects_unresolvable_ortholog_override_profile(tmp_path):
    app = create_app(job_store=JobStore(tmp_path / "jobs.sqlite3"))
    client = TestClient(app)

    response = client.post(
        "/jobs",
        json={
            "profile": "mtb-h37rv",
            "locus": "Rv0001",
            "allow_ortholog_fallback": True,
            "ortholog_override": {
                "profile_id": "not-a-real-profile",
                "locus": "X_0001",
            },
        },
    )

    assert response.status_code == 422


def test_job_submission_accepts_resolvable_ortholog_override_profile(tmp_path):
    app = create_app(
        job_store=JobStore(tmp_path / "jobs.sqlite3"),
        run_jobs_inline=False,
        start_worker=False,
    )
    client = TestClient(app)

    response = client.post(
        "/jobs",
        json={
            "profile": "mtb-h37rv",
            "locus": "Rv0001",
            "allow_ortholog_fallback": True,
            "ortholog_override": {
                "profile_id": "mtb-h37rv",
                "locus": "Rv9999",
                "name": "x",
            },
        },
    )

    assert response.status_code == 201
    assert response.json()["status"] == "queued"


def test_jobs_endpoint_lists_submitted_jobs_in_queue_order(tmp_path):
    app = create_app(
        job_store=JobStore(tmp_path / "jobs.sqlite3"),
        run_job=lambda request: {"annotation": {"gene_id": request.locus}},
        run_jobs_inline=False,
        start_worker=False,
    )
    client = TestClient(app)

    first = client.post(
        "/jobs",
        json={"profile": "mtb-h37rv", "locus": "Rv0001"},
    ).json()
    second = client.post(
        "/jobs",
        json={"profile": "mtb-h37rv", "locus": "Rv0002"},
    ).json()
    response = client.get("/jobs?order=queue")

    assert response.status_code == 200
    payload = response.json()
    assert [job["id"] for job in payload["jobs"]] == [
        first["job_id"],
        second["job_id"],
    ]
    assert payload["jobs"][0]["queue_position"] == 1
    assert payload["jobs"][1]["queue_position"] == 2
    assert payload["queue"]["queued"] == 2


def test_delete_jobs_history_clears_only_finished_jobs(tmp_path):
    store = JobStore(tmp_path / "jobs.sqlite3")
    app = create_app(
        job_store=store,
        run_job=lambda request: {"annotation": {"gene_id": request.locus}},
        run_jobs_inline=False,
        start_worker=False,
    )
    client = TestClient(app)
    completed = store.create_job({"profile": "mtb-h37rv", "locus": "Rv0001"})
    failed = store.create_job({"profile": "mtb-h37rv", "locus": "Rv0002"})
    queued = store.create_job({"profile": "mtb-h37rv", "locus": "Rv0003"})
    running = store.create_job({"profile": "mtb-h37rv", "locus": "Rv0004"})
    store.mark_completed(completed["id"], {"annotation": {"gene_id": "Rv0001"}})
    store.mark_failed(failed["id"], "bad paper")
    store.mark_running(running["id"])

    response = client.delete("/jobs/history")
    jobs_response = client.get("/jobs?order=queue")

    assert response.status_code == 200
    assert response.json() == {"deleted": 2}
    remaining_ids = {job["id"] for job in jobs_response.json()["jobs"]}
    assert remaining_ids == {queued["id"], running["id"]}


def test_completed_job_is_saved_to_annotation_store(tmp_path):
    class FakeAnnotationStore:
        def __init__(self):
            self.saved_jobs = []

        def health(self):
            return {"status": "ok"}

        def save_completed_job(self, job):
            self.saved_jobs.append(job)
            return "mtb-h37rv:Rv0001"

    annotation_store = FakeAnnotationStore()

    def fake_runner(request):
        return {
            "annotation": {
                "gene_id": request.locus,
                "name": "dnaA",
                "annotation_metadata": {"generated_at": "2026-01-01T00:00:00Z"},
            },
            "output_path": "gen_json/gen_Rv0001.json",
        }

    app = create_app(
        job_store=JobStore(tmp_path / "jobs.sqlite3"),
        annotation_store=annotation_store,
        run_job=fake_runner,
        run_jobs_inline=True,
    )
    client = TestClient(app)

    response = client.post(
        "/jobs",
        json={"profile": "mtb-h37rv", "locus": "Rv0001"},
    )

    assert response.status_code == 201
    assert response.json()["status"] == "completed"
    assert len(annotation_store.saved_jobs) == 1
    assert annotation_store.saved_jobs[0]["request"]["locus"] == "Rv0001"


def test_annotation_persistence_failure_is_visible_on_completed_job(tmp_path):
    class FailingAnnotationStore:
        def health(self):
            return {"status": "ok"}

        def save_completed_job(self, job):
            raise RuntimeError("mongo write failed")

    app = create_app(
        job_store=JobStore(tmp_path / "jobs.sqlite3"),
        annotation_store=FailingAnnotationStore(),
        run_job=lambda request: {"annotation": {"gene_id": request.locus}},
        run_jobs_inline=True,
    )
    client = TestClient(app)

    create_response = client.post(
        "/jobs",
        json={"profile": "mtb-h37rv", "locus": "Rv0001"},
    )
    job_response = client.get(f"/jobs/{create_response.json()['job_id']}")

    assert job_response.json()["status"] == "completed"
    assert job_response.json()["annotation_persisted"] is False
    assert job_response.json()["annotation_error"] == "mongo write failed"


def test_annotation_endpoints_use_annotation_store(tmp_path):
    class FakeAnnotationStore:
        def health(self):
            return {"status": "ok"}

        def search(self, query, limit=20):
            assert query == "dnaA"
            assert limit == 20
            return [
                {
                    "id": "mtb-h37rv:Rv0001",
                    "profile_id": "mtb-h37rv",
                    "canonical_name": "Mycobacterium tuberculosis H37Rv",
                    "normalized_locus": "Rv0001",
                    "gene_name": "dnaA",
                    "generated_at": "2026-01-01T00:00:00Z",
                    "version_count": 1,
                }
            ]

        def get(self, annotation_id):
            if annotation_id != "mtb-h37rv:Rv0001":
                return None
            return {
                "id": annotation_id,
                "profile_id": "mtb-h37rv",
                "canonical_name": "Mycobacterium tuberculosis H37Rv",
                "normalized_locus": "Rv0001",
                "gene_name": "dnaA",
                "generated_at": "2026-01-01T00:00:00Z",
                "result": {"annotation": {"gene_id": "Rv0001"}},
                "version_count": 1,
            }

        def get_versions(self, annotation_id):
            assert annotation_id == "mtb-h37rv:Rv0001"
            return [
                {
                    "version_id": "old-version",
                    "generated_at": "2025-12-01T00:00:00Z",
                    "job_id": "old-job",
                }
            ]

    app = create_app(
        job_store=JobStore(tmp_path / "jobs.sqlite3"),
        annotation_store=FakeAnnotationStore(),
        start_worker=False,
    )
    client = TestClient(app)

    search_response = client.get("/annotations/search?query=dnaA")
    detail_response = client.get("/annotations/mtb-h37rv:Rv0001")
    versions_response = client.get("/annotations/mtb-h37rv:Rv0001/versions")

    assert search_response.status_code == 200
    assert search_response.json()["matches"][0]["gene_name"] == "dnaA"
    assert detail_response.status_code == 200
    assert detail_response.json()["result"]["annotation"]["gene_id"] == "Rv0001"
    assert versions_response.status_code == 200
    assert versions_response.json()["versions"][0]["version_id"] == "old-version"


def test_annotation_endpoints_serialize_name_only_annotations(tmp_path):
    annotation_store = InMemoryAnnotationStore()
    annotation_id = annotation_store.save_completed_job({
        "id": "name-only-job",
        "request": {"organism": "Custom bacterium", "name": "abc1"},
        "result": {
            "annotation": {
                "gene_id": None,
                "name": "abc1",
                "annotation_metadata": {
                    "generated_at": "2026-01-01T00:00:00Z",
                    "profile_id": "ad-hoc-custom-bacterium",
                    "canonical_name": "Custom bacterium",
                    "species_name": "Custom bacterium",
                    "strain": None,
                    "resolved_locus": None,
                    "resolved_name": "abc1",
                    "profile_source": "ad_hoc",
                },
            }
        },
        "finished_at": "2026-01-01T00:00:00Z",
    })
    app = create_app(
        job_store=JobStore(tmp_path / "jobs.sqlite3"),
        annotation_store=annotation_store,
        start_worker=False,
    )
    client = TestClient(app, raise_server_exceptions=False)

    search_response = client.get("/annotations/search?query=abc1")
    detail_response = client.get(f"/annotations/{annotation_id}")

    assert search_response.status_code == 200
    assert search_response.json()["matches"][0]["normalized_locus"] is None
    assert detail_response.status_code == 200
    assert detail_response.json()["normalized_locus"] is None
    assert detail_response.json()["result"]["annotation"]["name"] == "abc1"


def test_annotation_search_rejects_unbounded_limit(tmp_path):
    class FakeAnnotationStore:
        def health(self):
            return {"status": "ok"}

        def search(self, query, limit=20):
            return []

    app = create_app(
        job_store=JobStore(tmp_path / "jobs.sqlite3"),
        annotation_store=FakeAnnotationStore(),
        start_worker=False,
    )
    client = TestClient(app)

    response = client.get("/annotations/search?query=dnaA&limit=1000")

    assert response.status_code == 422


def test_annotation_search_reports_store_runtime_errors_as_unavailable(tmp_path):
    class FailingAnnotationStore:
        def health(self):
            return {"status": "unavailable"}

        def search(self, query, limit=20):
            raise RuntimeError("mongo server is unreachable")

    app = create_app(
        job_store=JobStore(tmp_path / "jobs.sqlite3"),
        annotation_store=FailingAnnotationStore(),
        start_worker=False,
    )
    client = TestClient(app)

    response = client.get("/annotations/search?query=dnaA")

    assert response.status_code == 503
    assert response.json()["detail"] == "mongo server is unreachable"


def _regex_app(tmp_path):
    return create_app(job_store=JobStore(tmp_path / "jobs.sqlite3"))


def test_regex_from_examples_endpoint_returns_pattern(tmp_path):
    client = TestClient(_regex_app(tmp_path))

    response = client.post(
        "/regex/from-examples",
        json={"examples": ["Rv1000", "Rv2070c", "Rv3415A"]},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["regex"] == r"^Rv\d{4}[Ac]?$"
    assert all(entry["ok"] for entry in payload["matched"])


def test_regex_from_examples_endpoint_rejects_empty(tmp_path):
    client = TestClient(_regex_app(tmp_path))

    response = client.post("/regex/from-examples", json={"examples": ["  "]})

    assert response.status_code == 422


def test_regex_from_description_endpoint_returns_pattern(tmp_path, monkeypatch):
    monkeypatch.setattr(
        regex_gen,
        "regex_from_description",
        lambda description: {
            "regex": r"^Rv\d{4}[Ac]?$",
            "explanation": "Rv plus four digits.",
            "matched": [],
        },
    )
    client = TestClient(_regex_app(tmp_path))

    response = client.post(
        "/regex/from-description",
        json={"description": "Rv then 4 digits then c, A, or nothing"},
    )

    assert response.status_code == 200
    assert response.json()["regex"] == r"^Rv\d{4}[Ac]?$"


def test_regex_from_description_endpoint_reports_model_failure(tmp_path, monkeypatch):
    def _boom(description):
        raise regex_gen.RegexGenerationError("regex model is unavailable")

    monkeypatch.setattr(regex_gen, "regex_from_description", _boom)
    client = TestClient(_regex_app(tmp_path))

    response = client.post("/regex/from-description", json={"description": "anything"})

    assert response.status_code == 503


def test_regex_from_description_endpoint_requires_description(tmp_path):
    client = TestClient(_regex_app(tmp_path))

    response = client.post("/regex/from-description", json={"description": "   "})

    assert response.status_code == 422


def test_batch_schemas_import():
    from coordinator.schemas import (
        BatchCreateRequest,
        BatchCreateResponse,
        BatchDetailResponse,
        BatchEntryInput,
        BatchEntryPreview,
        BatchPreviewSummary,
        BatchValidateRequest,
        BatchValidateResponse,
    )

    assert BatchEntryInput(input="Rv0001").input == "Rv0001"


def _batch_app(tmp_path, **kwargs):
    return create_app(
        job_store=JobStore(tmp_path / "jobs.sqlite3"),
        run_jobs_inline=False,
        start_worker=False,
        **kwargs,
    )


def _patch_mtb_dnaa_lookup(monkeypatch, *, locus="Rv0202"):
    from autoannotation import gene_names

    def fake_lookup(profile, gene_name):
        if gene_name == "dnaA":
            return gene_names.GeneLocusLookupResult(
                locus=locus,
                source="annotation_table",
                confidence="profile_table",
            )
        return None

    monkeypatch.setattr(gene_names, "lookup_locus_from_annotation_table", fake_lookup)


def test_batches_validate_mtb_mixed_list(tmp_path, monkeypatch):
    _patch_mtb_dnaa_lookup(monkeypatch)
    client = TestClient(_batch_app(tmp_path))

    response = client.post(
        "/batches/validate",
        json={
            "profile": "mtb-h37rv",
            "entries": [
                {"input": "Rv0001"},
                {"input": "dnaA"},
                {"input": "not-a-real-gene"},
            ],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["summary"] == {
        "total": 3,
        "ready": 2,
        "ambiguous": 0,
        "invalid": 1,
        "duplicate_skipped": 0,
    }
    by_input = {entry["input"]: entry for entry in payload["entries"]}
    assert by_input["Rv0001"]["status"] == "ready"
    assert by_input["Rv0001"]["resolved_locus"] == "Rv0001"
    assert by_input["dnaA"]["status"] == "ready"
    assert by_input["dnaA"]["resolved_locus"] == "Rv0202"
    assert by_input["dnaA"]["match_method"] == "annotation_table"
    assert by_input["not-a-real-gene"]["status"] == "invalid"


def test_batches_create_queues_ready_jobs_only(tmp_path, monkeypatch):
    _patch_mtb_dnaa_lookup(monkeypatch, locus="Rv0001")
    client = TestClient(_batch_app(tmp_path))

    response = client.post(
        "/batches",
        json={
            "profile": "mtb-h37rv",
            "entries": [
                {"input": "Rv0001"},
                {"input": "dnaA"},
                {"input": "not-a-real-gene"},
            ],
            "allow_online_name_lookup": False,
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert len(payload["job_ids"]) == 1
    assert payload["summary"]["ready"] == 1
    assert payload["summary"]["duplicate_skipped"] == 1
    assert payload["summary"]["invalid"] == 1
    assert len(payload["skipped"]) == 2

    jobs_response = client.get("/jobs", params={"batch_id": payload["batch_id"]})
    assert jobs_response.status_code == 200
    assert len(jobs_response.json()["jobs"]) == 1
    assert jobs_response.json()["jobs"][0]["request"]["locus"] == "Rv0001"

    batch_response = client.get(f"/batches/{payload['batch_id']}")
    assert batch_response.status_code == 200
    batch_payload = batch_response.json()
    assert batch_payload["summary"]["ready"] == 1
    assert batch_payload["queue"]["queued"] == 1


def test_batch_entry_request_inherits_fallback_flag():
    from coordinator.schemas import BatchCreateRequest

    request = BatchCreateRequest(
        profile="mtb-h37rv",
        entries=[{"input": "Rv0001"}],
        allow_ortholog_fallback=True,
    )
    assert request.allow_ortholog_fallback is True


def test_create_batch_propagates_fallback_flag(tmp_path, monkeypatch):
    _patch_mtb_dnaa_lookup(monkeypatch, locus="Rv0001")
    client = TestClient(_batch_app(tmp_path))

    response = client.post(
        "/batches",
        json={
            "profile": "mtb-h37rv",
            "entries": [{"input": "Rv0001"}],
            "allow_online_name_lookup": False,
            "allow_ortholog_fallback": True,
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["job_ids"]

    jobs_response = client.get("/jobs", params={"batch_id": payload["batch_id"]})
    assert jobs_response.status_code == 200
    jobs = jobs_response.json()["jobs"]
    assert jobs
    assert all(
        job["request"]["allow_ortholog_fallback"] is True for job in jobs
    )
    assert all(job["request"].get("ortholog_override") is None for job in jobs)


def test_batches_rejects_empty(tmp_path):
    client = TestClient(_batch_app(tmp_path), raise_server_exceptions=False)

    create_response = client.post(
        "/batches",
        json={
            "profile": "mtb-h37rv",
            "entries": [{"input": "not-a-real-gene"}],
            "allow_online_name_lookup": False,
        },
    )
    assert create_response.status_code == 422
    assert create_response.json()["detail"] == "No ready entries to queue."

    parse_response = client.post(
        "/batches/validate",
        json={
            "profile": "mtb-h37rv",
            "raw_text": "\n\n# comment only\n",
            "entries": [{"input": "Rv0001"}],
        },
    )
    assert parse_response.status_code == 200


def test_batches_rejects_over_max_size(tmp_path, monkeypatch):
    monkeypatch.setattr("coordinator.api.MAX_BATCH_SIZE", 2)
    client = TestClient(_batch_app(tmp_path), raise_server_exceptions=False)

    response = client.post(
        "/batches/validate",
        json={
            "profile": "mtb-h37rv",
            "entries": [
                {"input": "Rv0001"},
                {"input": "Rv0002"},
                {"input": "Rv0003"},
            ],
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "Batch exceeds maximum size of 2."


def test_job_request_rejects_override_without_flag():
    import pytest
    from pydantic import ValidationError
    from coordinator.schemas import AnnotationJobRequest

    with pytest.raises(ValidationError):
        AnnotationJobRequest(
            profile="mtb-h37rv", locus="Rv0001",
            allow_ortholog_fallback=False,
            ortholog_override={"profile_id": "mtb-h37rv", "locus": "Rv9999"},
        )


def test_job_request_accepts_flag_and_override():
    from coordinator.schemas import AnnotationJobRequest

    request = AnnotationJobRequest(
        profile="mtb-h37rv", locus="Rv0001",
        allow_ortholog_fallback=True,
        ortholog_override={"profile_id": "mtb-h37rv", "locus": "Rv9999", "name": "x"},
    )
    assert request.allow_ortholog_fallback is True
    assert request.ortholog_override.locus == "Rv9999"


def test_job_request_flag_defaults_false():
    from coordinator.schemas import AnnotationJobRequest

    request = AnnotationJobRequest(profile="mtb-h37rv", locus="Rv0001")
    assert request.allow_ortholog_fallback is False
    assert request.ortholog_override is None


def _make_worker_client():
    from fastapi.testclient import TestClient

    from coordinator.annotation_store import InMemoryAnnotationStore
    from coordinator.api import create_app
    from coordinator.job_store import JobStore
    from coordinator.worker_registry import WorkerRegistry

    import tempfile, os
    db_path = os.path.join(tempfile.mkdtemp(), "jobs.sqlite3")
    store = JobStore(db_path)
    registry = WorkerRegistry(db_path)
    app = create_app(
        job_store=store,
        annotation_store=InMemoryAnnotationStore(),
        worker_registry=registry,
        start_worker=False,
        worker_api_token="test-token",
    )
    return TestClient(app), store


def _register_body():
    return {
        "worker_name": "w1",
        "hostname": "w1",
        "agent_version": "0.1.0",
        "total_memory_bytes": 64_000_000_000,
        "dedicated_memory_bytes": 42_000_000_000,
        "max_slots": 2,
        "ollama_models": ["llama3:8b"],
    }


def test_worker_endpoints_require_token():
    client, _ = _make_worker_client()
    response = client.post("/workers/register", json=_register_body())
    assert response.status_code == 401


def test_register_claim_complete_flow():
    client, store = _make_worker_client()
    headers = {"Authorization": "Bearer test-token"}

    reg = client.post("/workers/register", json=_register_body(), headers=headers)
    assert reg.status_code == 200
    worker_id = reg.json()["worker_id"]

    store.create_job(
        {"profile": "mtb-h37rv", "locus": "Rv0001", "cache_dir": "./.cache", "output_dir": "gen_json"}
    )

    claim = client.post(f"/workers/{worker_id}/claim", json={"free_slots": 2}, headers=headers)
    assert claim.status_code == 200
    job_id = claim.json()["job_id"]
    assert claim.json()["request"]["locus"] == "Rv0001"

    complete = client.post(
        f"/jobs/{job_id}/complete",
        json={"result": {"annotation": {"gene_id": "Rv0001"}}},
        headers=headers,
    )
    assert complete.status_code == 204
    assert store.get_job(job_id)["status"] == "completed"


def test_claim_returns_204_when_queue_empty():
    client, _ = _make_worker_client()
    headers = {"Authorization": "Bearer test-token"}
    worker_id = client.post("/workers/register", json=_register_body(), headers=headers).json()["worker_id"]
    claim = client.post(f"/workers/{worker_id}/claim", json={"free_slots": 2}, headers=headers)
    assert claim.status_code == 204


def test_health_includes_worker_summary():
    client, _ = _make_worker_client()
    headers = {"Authorization": "Bearer test-token"}
    client.post("/workers/register", json=_register_body(), headers=headers)
    health = client.get("/health").json()
    assert "workers" in health
    assert health["workers"]["total"] == 1
