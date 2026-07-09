import httpx
import pytest

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
