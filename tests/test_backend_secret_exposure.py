"""Secrets configured through the environment must never reach API responses or logs."""

import importlib.util
import json
import logging
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

from autoannotation import gene_names, http_
from autoannotation.pmc import PmcPaperManager
from backend.access import BOOTSTRAP_ADMIN_EMAIL
from backend.annotation_store import InMemoryAnnotationStore
from backend.job_store import JobStore
from shared.redact import redact_secrets_in, redact_url_secrets
from tests.auth_helpers import make_client, second_client, sign_in, worker_headers
from worker.runtime import JobSpec, WorkerRuntime

SENTINEL = "SENTINEL-"
SENTINEL_ENV = {
    "NCBI_API_KEY": "SENTINEL-NCBI_API_KEY",
    "WORKER_API_TOKEN": "SENTINEL-WORKER_API_TOKEN",
    "RESEND_API_KEY": "SENTINEL-RESEND_API_KEY",
    # Credentials in the URI are what must stay private; the unreachable port
    # makes Mongo fail fast so its error messages are exercised too.
    "MONGO_URI": "mongodb://sentinel:SENTINEL-MONGO_URI@127.0.0.1:9/annotations",
}
JOB = {"profile": "mtb-h37rv", "locus": "Rv0001", "allow_online_name_lookup": False}
REGISTER = {
    "worker_name": "w1",
    "hostname": "w1",
    "agent_version": "0.1.0",
    "total_memory_bytes": 64_000_000_000,
    "dedicated_memory_bytes": 42_000_000_000,
    "max_slots": 2,
    "ollama_models": ["llama3:8b"],
}
NCBI_URL_WITH_KEY = (
    "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pmc&id=1"
    "&api_key=SENTINEL-NCBI_API_KEY"
)


@pytest.fixture(autouse=True)
def sentinel_env(tmp_path, monkeypatch):
    monkeypatch.setenv("PROFILES_DIR", str(tmp_path / "profiles"))
    monkeypatch.delenv("MONGODB_URI", raising=False)
    for name, value in SENTINEL_ENV.items():
        monkeypatch.setenv(name, value)


def _assert_clean(response):
    assert response.status_code < 500, (response.request.url, response.text)
    assert SENTINEL not in response.text, (response.request.url, response.text)
    for name, value in response.headers.items():
        assert SENTINEL not in value, (response.request.url, name)


def _run_worker_flow(client, headers):
    """Complete one job and permanently fail another through the worker routes."""
    reg = client.post("/workers/register", json=REGISTER, headers=headers)
    _assert_clean(reg)
    worker_id = reg.json()["worker_id"]

    _assert_clean(client.get("/jobs/queue-summary", headers=headers))

    completed_id = client.post(
        f"/workers/{worker_id}/claim", json={"free_slots": 1}, headers=headers
    ).json()["job_id"]
    complete = client.post(
        f"/jobs/{completed_id}/complete",
        json={
            "worker_id": worker_id,
            "result": {
                "annotation": {"gene_id": "Rv0001", "summary": "DNA replication initiator"},
                "metadata": {
                    "gene_name_source": "ncbi_gene",
                    "gene_name_source_detail": NCBI_URL_WITH_KEY,
                },
            },
        },
        headers=headers,
    )
    assert complete.status_code == 204

    failed_id = client.post(
        f"/workers/{worker_id}/claim", json={"free_slots": 1}, headers=headers
    ).json()["job_id"]
    fail = client.post(
        f"/jobs/{failed_id}/fail",
        json={
            "worker_id": worker_id,
            "error": f"HTTPError: 500 Server Error for url: {NCBI_URL_WITH_KEY}",
            "retryable": False,
        },
        headers=headers,
    )
    assert fail.status_code == 204
    return completed_id, failed_id


def _check_all_endpoints(user, admin, job_ids, completed_id=None):
    for client in (user, admin):
        for path in ("/auth/me", "/jobs", "/profiles", "/jobs/queue-status", "/healthz"):
            _assert_clean(client.get(path))
        for job_id in job_ids:
            _assert_clean(client.get(f"/jobs/{job_id}"))
            if job_id != completed_id:
                _assert_clean(client.get(f"/jobs/{job_id}/result"))
        if completed_id is not None:
            result = client.get(f"/jobs/{completed_id}/result")
            assert result.status_code == 200
            _assert_clean(result)
    for path in ("/health", "/backend-info", "/workers"):
        response = admin.get(path)
        assert response.status_code == 200
        _assert_clean(response)


class _RecordingAnnotationStore(InMemoryAnnotationStore):
    def __init__(self):
        super().__init__()
        self.saved_jobs = []

    def save_completed_job(self, job):
        self.saved_jobs.append(job)
        return super().save_completed_job(job)


@pytest.mark.parametrize("token_source", ["explicit", "env"])
def test_secrets_never_appear_in_api_responses_or_logs(tmp_path, caplog, token_source):
    caplog.set_level(logging.DEBUG)
    annotation_store = None
    if token_source == "explicit":
        annotation_store = _RecordingAnnotationStore()
        client = make_client(tmp_path, annotation_store=annotation_store)
        headers = worker_headers()
    else:
        # Worker token and Mongo URI both come from the sentinel environment.
        client = make_client(tmp_path, worker_api_token=None, annotation_store=None)
        headers = {"Authorization": f"Bearer {SENTINEL_ENV['WORKER_API_TOKEN']}"}

    with client:
        user = sign_in(client)
        admin = second_client(user, BOOTSTRAP_ADMIN_EMAIL)
        user_jobs = [user.post("/jobs", json=JOB) for _ in range(2)]
        for response in user_jobs:
            _assert_clean(response)
        job_ids = [response.json()["job_id"] for response in user_jobs]

        _check_all_endpoints(user, admin, job_ids)
        completed_id, failed_id = _run_worker_flow(user, headers)
        assert {completed_id, failed_id} == set(job_ids)
        assert "api_key=" in admin.get(f"/jobs/{failed_id}").json()["error"]

        _check_all_endpoints(user, admin, job_ids, completed_id)
        detail = user.get(f"/jobs/{completed_id}/result").json()["metadata"]
        assert detail["gene_name_source_detail"].endswith("api_key=REDACTED")

        stored = JobStore(client.auth_store.db_path).get_job(completed_id)
        assert SENTINEL not in json.dumps(stored["result"])

    if annotation_store is not None:
        assert len(annotation_store.saved_jobs) == 1
        assert SENTINEL not in json.dumps(annotation_store.saved_jobs[0], default=str)
        assert SENTINEL not in json.dumps(annotation_store._documents, default=str)
    assert SENTINEL not in caplog.text


def test_results_stored_before_redaction_are_scrubbed_on_read(tmp_path):
    client = make_client(tmp_path)
    user = sign_in(client)
    admin = second_client(user, BOOTSTRAP_ADMIN_EMAIL)
    job_id = user.post("/jobs", json=JOB).json()["job_id"]
    store = JobStore(client.auth_store.db_path)
    store.mark_completed(
        job_id,
        {"metadata": {"gene_name_source_detail": NCBI_URL_WITH_KEY}, "papers": [NCBI_URL_WITH_KEY]},
    )
    assert SENTINEL in json.dumps(store.get_job(job_id)["result"])

    for viewer in (user, admin):
        for path in (f"/jobs/{job_id}", f"/jobs/{job_id}/result", "/jobs"):
            response = viewer.get(path)
            assert response.status_code == 200
            _assert_clean(response)
    result = user.get(f"/jobs/{job_id}/result").json()
    assert result["metadata"]["gene_name_source_detail"].endswith("db=pmc&id=1&api_key=REDACTED")


def test_worker_token_is_rejected_when_wrong_without_echoing_it(tmp_path):
    client = make_client(tmp_path, worker_api_token=None)
    response = client.post(
        "/workers/register",
        json=REGISTER,
        headers={"Authorization": "Bearer SENTINEL-wrong-token"},
    )
    assert response.status_code == 401
    assert SENTINEL not in response.text


def test_redact_url_secrets_masks_api_key_values():
    text = f"failed for url: {NCBI_URL_WITH_KEY} (retrying)"
    redacted = redact_url_secrets(text)
    assert SENTINEL not in redacted
    assert "api_key=REDACTED" in redacted
    assert "db=pmc&id=1" in redacted
    assert redact_url_secrets("no secrets here") == "no secrets here"
    assert redact_url_secrets(None) is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("(url: /x?api_key=SENTINEL-k)", "(url: /x?api_key=REDACTED)"),
        ("api_key=SENTINEL-k, next", "api_key=REDACTED, next"),
        ("api_key=SENTINEL-k; next", "api_key=REDACTED; next"),
        ('{"u": "a?api_key=SENTINEL-k"}', '{"u": "a?api_key=REDACTED"}'),
        ('"a?api_key=SENTINEL-k\\"x"', '"a?api_key=REDACTED\\"x"'),
        ("q%3Fdb%3Dpmc%26api_key%3DSENTINEL-k%26id%3D1", "q%3Fdb%3Dpmc%26api_key%3DREDACTED%26id%3D1"),
        ("x?api%5Fkey=SENTINEL-k&id=1", "x?api%5Fkey=REDACTED&id=1"),
        ("x?API%5FKEY%3dSENTINEL-k", "x?API%5FKEY%3dREDACTED"),
        ("NCBI_API_KEY=SENTINEL-k", "NCBI_API_KEY=REDACTED"),
    ],
)
def test_redact_url_secrets_stop_set_and_encoded_forms(text, expected):
    assert redact_url_secrets(text) == expected


def test_redact_secrets_in_walks_nested_json_without_touching_other_values():
    payload = {
        "metadata": {"gene_name_source_detail": NCBI_URL_WITH_KEY, "count": 3},
        "papers": [{"url": NCBI_URL_WITH_KEY}, None, 1.5, True],
        "pair": ("a", NCBI_URL_WITH_KEY),
    }

    redacted = redact_secrets_in(payload)

    assert SENTINEL not in json.dumps(redacted)
    assert redacted["metadata"]["count"] == 3
    assert redacted["papers"][1:] == [None, 1.5, True]
    assert SENTINEL in payload["metadata"]["gene_name_source_detail"]


def _load_mongo_script():
    path = Path(__file__).resolve().parent.parent / "scripts" / "redact_mongo_secrets.py"
    spec = importlib.util.spec_from_file_location("redact_mongo_secrets", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_mongo_script_transform_redacts_only_affected_documents():
    script = _load_mongo_script()
    marker = object()
    documents = [
        {"_id": "clean", "search_text": "dnaA replication", "versions": []},
        {
            "_id": "dirty",
            "created": marker,
            "latest": {"result": {"metadata": {"gene_name_source_detail": NCBI_URL_WITH_KEY}}},
            "versions": [{"result": {"papers": [NCBI_URL_WITH_KEY]}}],
            "search_text": f"dnaA {NCBI_URL_WITH_KEY}",
        },
    ]

    matches = list(script.find_redactions(documents))

    assert [document_id for document_id, _ in matches] == ["dirty"]
    redacted = matches[0][1]
    assert redacted["_id"] == "dirty"
    assert redacted["created"] is marker
    assert SENTINEL not in json.dumps(redacted, default=str)
    assert "api_key=REDACTED" in redacted["latest"]["result"]["metadata"]["gene_name_source_detail"]
    assert SENTINEL in documents[1]["search_text"]


def test_mongo_script_keeps_original_id_even_if_it_matches():
    script = _load_mongo_script()
    document = {"_id": "x?api_key=SENTINEL-k", "detail": NCBI_URL_WITH_KEY}

    redacted, changed = script.redact_document(document)

    assert changed
    assert redacted["_id"] == document["_id"]
    assert SENTINEL not in redacted["detail"]


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload
        self.status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeNcbiSession:
    def __init__(self, fail_summary=False):
        self.fail_summary = fail_summary
        self.urls = []

    def get(self, url, timeout=None):
        self.urls.append(url)
        if "esearch" in url:
            return _FakeResponse({"esearchresult": {"idlist": ["42"]}})
        if self.fail_summary:
            raise requests.ConnectionError(f"Max retries exceeded with url: {url}")
        return _FakeResponse({"result": {"42": {"name": "dnaA", "otheraliases": ""}}})


@pytest.mark.parametrize("fail_summary", [False, True])
def test_ncbi_gene_source_detail_never_carries_api_key(fail_summary):
    profile = type("Profile", (), {"species_name": "Mycobacterium tuberculosis"})()
    session = _FakeNcbiSession(fail_summary=fail_summary)

    result = gene_names.NcbiGeneSource(session=session).lookup(profile, "Rv0001")

    assert all("api_key=SENTINEL-NCBI_API_KEY" in url for url in session.urls)
    assert result.source_detail
    assert SENTINEL not in result.source_detail
    assert SENTINEL not in " ".join(result.warnings)


def test_cached_gene_name_source_detail_is_redacted(tmp_path):
    profile = type("Profile", (), {"profile_id": "p1"})()
    gene_names.write_cached_gene_name(
        gene_names.GeneNameRecord(
            profile_id="p1",
            locus="Rv0001",
            gene_name="dnaA",
            source="ncbi_gene",
            source_detail=NCBI_URL_WITH_KEY,
            confidence="clear",
            aliases=[],
            looked_up_at="2026-01-01T00:00:00+00:00",
        ),
        tmp_path,
    )

    result = gene_names.lookup_cached_gene_name(profile, "Rv0001", tmp_path)

    assert result.gene_name == "dnaA"
    assert SENTINEL not in result.source_detail


def test_throttler_retry_warning_redacts_api_key(caplog, monkeypatch):
    caplog.set_level(logging.DEBUG)
    monkeypatch.setenv("AUTOANNOTATION_HTTP_GET_ATTEMPTS", "2")
    monkeypatch.setenv("AUTOANNOTATION_HTTP_RETRY_BACKOFF_SEC", "0")
    throttler = http_.Throttler(cooldown_secs=0)

    def always_fails():
        raise requests.ConnectionError(f"Max retries exceeded with url: {NCBI_URL_WITH_KEY}")

    with pytest.raises(requests.ConnectionError):
        throttler.throttle("https://eutils.ncbi.nlm.nih.gov/", always_fails)

    assert "retrying" in caplog.text
    assert SENTINEL not in caplog.text


def test_worker_fail_report_redacts_api_key():
    from worker.client import BackendClient

    sent = {}

    class _Http:
        def post(self, path, **kwargs):
            sent.update(kwargs.get("json") or {})
            return _Resp()

    class _Resp:
        status_code = 204

        def raise_for_status(self):
            return None

    config = type("Config", (), {"backend_url": "http://backend", "worker_api_token": "t"})()
    client = BackendClient(config, http_client=_Http())
    client.fail("job-1", f"subprocess failed: {NCBI_URL_WITH_KEY}", retryable=False)

    assert "api_key=REDACTED" in sent["error"]
    assert SENTINEL not in sent["error"]


class _FailingThrottler:
    def get(self, url, base_url):
        raise requests.ConnectionError(f"Max retries exceeded with url: {url}")


class _SearchOnlyPmcPaperManager(PmcPaperManager):
    def __init__(self):
        self._configure_organism_profile(None)
        self.throttler = _FailingThrottler()


def test_pmc_elink_failure_warning_redacts_api_key(caplog):
    caplog.set_level(logging.DEBUG)

    pmc_ids = _SearchOnlyPmcPaperManager()._get_pmc_ids_for_pubmed_ids(["123"])

    assert pmc_ids == []
    assert "PubMed-to-PMC elink failed" in caplog.text
    assert "api_key=REDACTED" in caplog.text
    assert SENTINEL not in caplog.text


class _RecordingJobSource:
    def __init__(self, jobs):
        self._jobs = list(jobs)
        self.failed = []

    def claim_one(self):
        return self._jobs.pop(0) if self._jobs else None

    def on_complete(self, job_id, result):
        raise AssertionError("job should fail")

    def on_fail(self, job_id, error, retryable):
        self.failed.append((job_id, error, retryable))

    def is_exhausted(self):
        return not self._jobs

    def wait_or_sleep(self, timeout):
        time.sleep(min(timeout, 0.01))


def test_worker_runtime_failure_log_and_report_redact_api_key(caplog):
    caplog.set_level(logging.DEBUG)
    source = _RecordingJobSource([JobSpec(job_id="j1", request={"locus": "Rv0001"})])

    def execute(request):
        raise RuntimeError(f"annotation subprocess failed: {NCBI_URL_WITH_KEY}")

    WorkerRuntime(
        config=SimpleNamespace(max_slots=1, heartbeat_seconds=15),
        fleet_config=SimpleNamespace(max_slots=1),
        job_source=source,
        execute_fn=execute,
    ).run()

    assert len(source.failed) == 1
    assert "api_key=REDACTED" in source.failed[0][1]
    assert SENTINEL not in source.failed[0][1]
    assert "Failed job j1" in caplog.text
    assert SENTINEL not in caplog.text


def test_outbound_ncbi_requests_still_carry_the_key():
    assert http_.ncbi_api_key_param() == "&api_key=SENTINEL-NCBI_API_KEY"
