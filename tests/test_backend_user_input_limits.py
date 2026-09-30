import subprocess
from pathlib import Path

import pytest

from autoannotation import batch_resolution, targets
from backend import api as backend_api
from backend import email_sender
from backend.access import BOOTSTRAP_ADMIN_EMAIL
from backend.job_store import JobStore
from tests.auth_helpers import make_client, second_client, sign_in, signed_in_client

REPO_ROOT = Path(__file__).resolve().parents[1]
JOB = {"profile": "mtb-h37rv", "locus": "Rv0001", "allow_online_name_lookup": False}
BATCH = {
    "profile": "mtb-h37rv",
    "entries": [{"input": "Rv0001"}, {"input": "Rv0002"}],
    "allow_online_name_lookup": False,
}
AD_HOC = {"organism": "Custom bacterium", "name": "abc1", "allow_online_name_lookup": False}
AD_HOC_BATCH = {
    "organism": "Custom bacterium",
    "entries": [{"input": "abc1"}],
    "allow_online_name_lookup": False,
}
PATTERN_VALUES = {
    "locus_regex": "^(a+)+$",
    "search_terms": ["Custom bacterium"],
    "target_patterns": ["(a|aa)+$"],
    "off_target_patterns": ["Other"],
    "excluded_species_patterns": ["Excluded"],
}
ENDPOINT_BODIES = {
    "/validate": AD_HOC,
    "/jobs": AD_HOC,
    "/batches/validate": AD_HOC_BATCH,
    "/batches": AD_HOC_BATCH,
}


@pytest.fixture(autouse=True)
def isolate_env(tmp_path, monkeypatch):
    monkeypatch.setenv("PROFILES_DIR", str(tmp_path / "profiles"))
    monkeypatch.delenv("MONGO_URI", raising=False)
    monkeypatch.delenv("MONGODB_URI", raising=False)
    monkeypatch.delenv("SUBMISSIONS_PAUSED", raising=False)


@pytest.mark.parametrize("endpoint", list(ENDPOINT_BODIES))
@pytest.mark.parametrize("field", list(PATTERN_VALUES))
def test_users_cannot_supply_patterns(tmp_path, endpoint, field):
    client = signed_in_client(tmp_path)
    body = {**ENDPOINT_BODIES[endpoint], field: PATTERN_VALUES[field]}

    response = client.post(endpoint, json=body)

    assert response.status_code == 422
    assert field in response.json()["detail"]
    assert "admin" in response.json()["detail"].lower()


@pytest.mark.parametrize("endpoint", list(ENDPOINT_BODIES))
def test_empty_pattern_defaults_are_treated_as_absent(tmp_path, endpoint):
    client = signed_in_client(tmp_path)
    body = {
        **ENDPOINT_BODIES[endpoint],
        "locus_regex": "  ",
        "search_terms": [],
        "target_patterns": [],
        "off_target_patterns": [],
        "excluded_species_patterns": [],
    }

    response = client.post(endpoint, json=body)

    assert response.status_code in (200, 201), response.text


@pytest.mark.parametrize("endpoint", list(ENDPOINT_BODIES))
def test_admins_may_supply_patterns(tmp_path, endpoint):
    client = signed_in_client(tmp_path, email=BOOTSTRAP_ADMIN_EMAIL)
    body = {
        **ENDPOINT_BODIES[endpoint],
        "locus_regex": r"^CUS_\d+$",
        "search_terms": ["Custom bacterium"],
    }
    if "entries" in body:
        body["entries"] = [{"input": "CUS_0001"}]

    response = client.post(endpoint, json=body)

    assert response.status_code in (200, 201), response.text


@pytest.mark.parametrize(
    "endpoint, body",
    [
        ("/validate", {"profile": "mtb-h37rv", "locus": "R" * 129}),
        ("/validate", {"profile": "mtb-h37rv", "name": "n" * 129}),
        ("/jobs", {"profile": "mtb-h37rv", "locus": "R" * 129}),
        ("/validate", {"organism": "O" * 201, "name": "abc1"}),
        ("/batches/validate", {"profile": "mtb-h37rv", "entries": [{"input": "R" * 129}]}),
        ("/batches", {"profile": "mtb-h37rv", "entries": [{"locus": "R" * 129}]}),
    ],
)
def test_overlong_identifiers_are_rejected(tmp_path, endpoint, body):
    client = signed_in_client(tmp_path, email=BOOTSTRAP_ADMIN_EMAIL)

    assert client.post(endpoint, json=body).status_code == 422


def test_overlong_username_is_rejected(tmp_path):
    client = make_client(tmp_path)

    response = client.post(
        "/auth/signup",
        json={"email": "a@example.com", "username": "u" * 65, "accept_terms": True},
    )

    assert response.status_code == 422


def test_validation_lookups_are_rate_limited_per_ip(tmp_path, monkeypatch):
    monkeypatch.setenv("IP_VALIDATIONS_PER_HOUR", "2")
    alice = signed_in_client(tmp_path, email="alice@example.com")
    bob = second_client(alice, email="bob@example.com")

    assert alice.post("/validate", json=JOB).status_code == 200
    assert alice.post("/batches/validate", json=BATCH).status_code == 200
    response = bob.post("/validate", json=JOB)

    assert response.status_code == 429
    assert response.json()["code"] == "rate_limited"
    assert bob.post("/batches/validate", json=BATCH).json()["code"] == "rate_limited"


def test_admins_are_exempt_from_validation_limit(tmp_path, monkeypatch):
    monkeypatch.setenv("IP_VALIDATIONS_PER_HOUR", "1")
    admin = signed_in_client(tmp_path, email=BOOTSTRAP_ADMIN_EMAIL)

    for _ in range(3):
        assert admin.post("/validate", json=JOB).status_code == 200


def test_zero_validation_limit_means_unlimited(tmp_path, monkeypatch):
    monkeypatch.setenv("IP_VALIDATIONS_PER_HOUR", "0")
    client = signed_in_client(tmp_path)

    for _ in range(3):
        assert client.post("/validate", json=JOB).status_code == 200


def test_submit_limit_is_checked_before_target_resolution(tmp_path, monkeypatch):
    monkeypatch.setenv("IP_SUBMITS_PER_HOUR", "1")
    client = signed_in_client(tmp_path)
    assert client.post("/jobs", json=JOB).status_code == 201

    def no_lookups(*_args, **_kwargs):
        raise AssertionError("rate-limited submissions must not resolve targets")

    monkeypatch.setattr(targets, "resolve_annotation_target", no_lookups)
    monkeypatch.setattr(batch_resolution, "resolve_batch_entry", no_lookups)

    assert client.post("/jobs", json=JOB).json()["code"] == "rate_limited"
    assert client.post("/batches", json=BATCH).json()["code"] == "rate_limited"


def test_paused_submission_does_not_consume_submit_limit(tmp_path, monkeypatch):
    monkeypatch.setenv("IP_SUBMITS_PER_HOUR", "1")
    client = signed_in_client(tmp_path)
    monkeypatch.setenv("SUBMISSIONS_PAUSED", "1")
    assert client.post("/jobs", json=JOB).status_code == 503
    monkeypatch.delenv("SUBMISSIONS_PAUSED")

    assert client.post("/jobs", json=JOB).status_code == 201


def test_rejected_target_does_not_consume_submit_limit(tmp_path, monkeypatch):
    monkeypatch.setenv("IP_SUBMITS_PER_HOUR", "1")
    client = signed_in_client(tmp_path)
    assert client.post("/jobs", json={**JOB, "locus": "not-a-locus"}).status_code == 422

    assert client.post("/jobs", json=JOB).status_code == 201


def test_client_supplied_profile_config_never_reaches_workers(tmp_path):
    job_store = JobStore(tmp_path / "jobs.sqlite3")
    client = sign_in(make_client(tmp_path, job_store=job_store))

    created = client.post(
        "/jobs",
        json={**AD_HOC, "profile_config": {"locus_regex": "^(a+)+$", "source": "local"}},
    )

    assert created.status_code == 201, created.text
    stored = job_store.get_job(created.json()["job_id"])["request"]
    assert stored.get("profile_config") is None


def test_named_profile_config_is_rederived_not_client_supplied(tmp_path):
    job_store = JobStore(tmp_path / "jobs.sqlite3")
    client = sign_in(make_client(tmp_path, job_store=job_store))

    created = client.post("/jobs", json={**JOB, "profile_config": {"locus_regex": "^(a+)+$"}})

    stored = job_store.get_job(created.json()["job_id"])["request"]
    assert stored["profile_config"]["profile_id"] == "mtb-h37rv"
    assert stored["profile_config"]["locus_regex"] != "^(a+)+$"


def test_failed_job_errors_are_generic_for_users(tmp_path):
    job_store = JobStore(tmp_path / "jobs.sqlite3")
    user = sign_in(make_client(tmp_path, job_store=job_store))
    admin = second_client(user, email=BOOTSTRAP_ADMIN_EMAIL)
    job_id = user.post("/jobs", json=JOB).json()["job_id"]
    job_store.mark_failed(job_id, "Traceback: /srv/internal/path.py line 3")
    job_store.mark_annotation_error(job_id, "mongo auth failed for user gaa")

    user_view = user.get(f"/jobs/{job_id}").json()
    listed = next(job for job in user.get("/jobs").json()["jobs"] if job["id"] == job_id)
    admin_view = admin.get(f"/jobs/{job_id}").json()

    for view in (user_view, listed):
        assert view["error"] == "Job failed"
        assert "annotation_error" not in view
    assert admin_view["error"].startswith("Traceback")
    assert admin_view["annotation_error"] == "mongo auth failed for user gaa"


def test_cancel_reason_stays_visible_to_users(tmp_path):
    client = signed_in_client(tmp_path)
    job_id = client.post("/jobs", json=JOB).json()["job_id"]

    assert client.post(f"/jobs/{job_id}/cancel").json()["error"] == "Cancelled by user"


@pytest.mark.parametrize("path", ["/auth/signup", "/auth/login"])
def test_login_code_delivery_failure_is_generic(tmp_path, monkeypatch, caplog, path):
    client = make_client(tmp_path)
    if path == "/auth/login":
        sign_in(make_client(tmp_path), email="a@example.com")

    def broken_provider(**_kwargs):
        raise RuntimeError("resend rejected key re_SECRET123")

    monkeypatch.setattr(email_sender, "send_login_code_email", broken_provider)
    body = {"email": "a@example.com", "accept_terms": True}

    with caplog.at_level("ERROR"):
        response = client.post(path, json=body)

    assert response.status_code == 502
    assert "re_SECRET123" not in response.text
    assert "re_SECRET123" in caplog.text


@pytest.mark.parametrize(
    "name", ["LEASE_SECONDS", "MAX_ATTEMPTS", "WORKER_OFFLINE_SECONDS"]
)
@pytest.mark.parametrize("raw", ["six hours", "0", "-5"])
def test_bad_numeric_env_falls_back_to_default(tmp_path, monkeypatch, caplog, name, raw):
    monkeypatch.setenv(name, raw)

    with caplog.at_level("WARNING"):
        client = signed_in_client(tmp_path)

    assert client.post("/jobs", json=JOB).status_code == 201
    assert name in caplog.text


def test_positive_env_int_helper(monkeypatch):
    monkeypatch.setenv("MAX_BATCH_SIZE", "lots")
    assert backend_api._positive_env_int("MAX_BATCH_SIZE", 2000) == 2000
    monkeypatch.setenv("MAX_BATCH_SIZE", "0")
    assert backend_api._positive_env_int("MAX_BATCH_SIZE", 2000) == 2000
    monkeypatch.setenv("MAX_BATCH_SIZE", "50")
    assert backend_api._positive_env_int("MAX_BATCH_SIZE", 2000) == 50
    monkeypatch.delenv("MAX_BATCH_SIZE")
    assert backend_api._positive_env_int("MAX_BATCH_SIZE", 2000) == 2000


@pytest.mark.parametrize("flag", ["on", "ON", "True"])
def test_trust_forwarded_for_matches_env_flag_spellings(monkeypatch, flag):
    from backend.client_ip import client_ip

    class Req:
        headers = {"x-forwarded-for": "9.9.9.9"}
        client = None

    monkeypatch.setenv("TRUST_FORWARDED_FOR", flag)
    assert client_ip(Req) == "9.9.9.9"


def test_preflight_combined_requires_worker_token_enforcement(tmp_path):
    env = tmp_path / ".env"
    env.write_text(
        "MONGO_URI=mongodb://x\n"
        "WORKER_API_TOKEN=tok\n"
        "REQUIRE_WORKER_API_TOKEN=0\n"
        "SESSION_COOKIE_SECURE=1\n"
        "EMAIL_BACKEND=console\n"
    )

    result = subprocess.run(
        [str(REPO_ROOT / "deploy" / "scripts" / "preflight-env.sh"), str(env)],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )

    assert result.returncode == 1
    assert "INVALID REQUIRE_WORKER_API_TOKEN" in result.stdout
