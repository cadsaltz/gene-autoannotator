import httpx
import pytest

from worker.fleet.config import FleetConfig
from worker.router import Backend, ModelRouter
from worker.router.client import RouterClient
from worker.router.server import start_router_server


@pytest.fixture
def router_server(monkeypatch):
    router = ModelRouter(
        [Backend(host="http://127.0.0.1:11434", models={"gemma3:1b"}, parallel=1)]
    )

    class FakeClient:
        def __init__(self, host: str) -> None:
            self.host = host

        def chat(self, **kwargs):
            return {
                "model": kwargs["model"],
                "message": {"role": "assistant", "content": "{}"},
                "done": True,
            }

    monkeypatch.setattr("worker.router.server.ollama.Client", FakeClient)

    thread = start_router_server(router, "127.0.0.1", 0)
    base_url = f"http://127.0.0.1:{thread._port}"
    yield base_url, thread
    thread._server.shutdown()
    thread._server.server_close()
    thread.join(timeout=2.0)


def test_health_returns_ok(router_server):
    base_url, _thread = router_server
    response = httpx.get(f"{base_url}/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_chat_proxies_to_ollama_and_returns_routing_metadata(router_server):
    base_url, _thread = router_server
    client = RouterClient(base_url)
    result = client.chat(
        model="gemma3:1b",
        messages=[{"role": "user", "content": "hi"}],
        role="gene_aggregation",
        job_id="job-1",
    )
    assert result["backend"] == "http://127.0.0.1:11434"
    assert "queue_wait_ms" in result
    assert result["message"]["content"] == "{}"


def test_metrics_records_chat_calls_when_enabled(monkeypatch):
    router = ModelRouter(
        [Backend(host="http://127.0.0.1:11434", models={"gemma3:1b"}, parallel=1)]
    )
    fleet_cfg = FleetConfig(num_servers=1, parallel=1, max_slots=1)

    class FakeClient:
        def __init__(self, host: str) -> None:
            self.host = host

        def chat(self, **kwargs):
            return {
                "model": kwargs["model"],
                "message": {"role": "assistant", "content": "{}"},
                "done": True,
                "eval_duration": 2_000_000_000,
                "total_duration": 2_500_000_000,
            }

    monkeypatch.setattr("worker.router.server.ollama.Client", FakeClient)

    thread = start_router_server(
        router,
        "127.0.0.1",
        0,
        collect_metrics=True,
        fleet_cfg=fleet_cfg,
        jobs_submitted=1,
        model_mode="nano",
    )
    base_url = f"http://127.0.0.1:{thread._port}"
    try:
        client = RouterClient(base_url)
        client.chat(
            model="gemma3:1b",
            messages=[{"role": "user", "content": "hi"}],
            role="gene_aggregation",
            job_id="job-1",
        )
        response = httpx.get(f"{base_url}/metrics")
        assert response.status_code == 200
        report = response.json()
        assert report["primary_kpi"] == "jobs_per_hour"
        assert report["per_model"]["gemma3:1b"]["calls"] == 1
        assert report["per_model"]["gemma3:1b"]["p50_queue_wait_ms"] >= 0
    finally:
        thread._server.shutdown()
        thread._server.server_close()
        thread.join(timeout=2.0)
