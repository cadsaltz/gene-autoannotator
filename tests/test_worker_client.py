import json

import httpx

from worker.client import CoordinatorClient
from worker.config import WorkerConfig


def _config():
    return WorkerConfig(
        coordinator_url="http://coordinator.test",
        worker_api_token="tok",
        worker_name="w1",
        hostname="w1",
        dedicated_memory_bytes=42_000_000_000,
        total_memory_bytes=64_000_000_000,
        max_slots=1,
        agent_version="0.1.0",
    )


def test_progress_sends_structured_fields():
    captured = {}

    def handler(request):
        captured["path"] = request.url.path
        captured["json"] = json.loads(request.content)
        return httpx.Response(204)

    http = httpx.Client(
        base_url="http://coordinator.test",
        transport=httpx.MockTransport(handler),
    )
    client = CoordinatorClient(_config(), http_client=http)

    client.progress(
        "job-1",
        "extracting 2/9 sections (target)",
        phase="extracting",
        sections_done=2,
        sections_total=9,
        pass_name="target",
    )

    assert captured["path"] == "/jobs/job-1/progress"
    assert captured["json"] == {
        "current_step": "extracting 2/9 sections (target)",
        "phase": "extracting",
        "sections_done": 2,
        "sections_total": 9,
        "pass_name": "target",
    }


def test_deregister_deletes_the_registered_worker():
    captured = {}

    def handler(request):
        captured["method"] = request.method
        captured["path"] = request.url.path
        captured["authorization"] = request.headers.get("authorization")
        return httpx.Response(204)

    http = httpx.Client(
        base_url="http://coordinator.test",
        transport=httpx.MockTransport(handler),
    )
    client = CoordinatorClient(_config(), http_client=http)
    client.worker_id = "worker-1"

    client.deregister()

    assert captured["method"] == "DELETE"
    assert captured["path"] == "/workers/worker-1"
    assert captured["authorization"] == "Bearer tok"


def test_deregister_is_a_noop_before_registration():
    def handler(request):
        raise AssertionError(f"unexpected request: {request.url}")

    http = httpx.Client(
        base_url="http://coordinator.test",
        transport=httpx.MockTransport(handler),
    )

    CoordinatorClient(_config(), http_client=http).deregister()


def test_progress_minimal_payload_omits_optional_fields():
    captured = {}

    def handler(request):
        captured["json"] = json.loads(request.content)
        return httpx.Response(204)

    http = httpx.Client(
        base_url="http://coordinator.test",
        transport=httpx.MockTransport(handler),
    )
    client = CoordinatorClient(_config(), http_client=http)

    client.progress("job-1", "running")

    assert captured["json"] == {"current_step": "running"}
