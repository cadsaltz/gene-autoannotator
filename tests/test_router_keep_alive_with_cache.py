import httpx

from worker.router import Backend, ModelRouter
from worker.router.server import start_router_server


def test_chat_keep_alive_not_forced_to_minus_one_when_cache_present(monkeypatch):
    """Regression: ModelMemoryCache must not overwrite operator keep_alive to -1."""
    monkeypatch.setenv("AUTOANNOTATION_OLLAMA_KEEP_ALIVE", "5m")
    captured: dict = {}

    router = ModelRouter(
        [Backend(host="http://127.0.0.1:11434", models={"gemma3:1b"}, parallel=1)]
    )

    class DummyCache:
        def ensure(self, model):
            return None

        def release(self, model):
            return None

    def fake_chat(host, *, model, messages, format=None, keep_alive=None, timeout_sec):
        captured["keep_alive"] = keep_alive
        return {
            "model": model,
            "message": {"role": "assistant", "content": "{}"},
            "done": True,
        }

    monkeypatch.setattr("worker.router.server.ollama_chat_http", fake_chat)

    thread = start_router_server(
        router, "127.0.0.1", 0, model_cache=DummyCache()
    )
    base_url = f"http://127.0.0.1:{thread._port}"
    try:
        response = httpx.post(
            f"{base_url}/v1/chat",
            json={
                "model": "gemma3:1b",
                "messages": [{"role": "user", "content": "hi"}],
                "role": "section_summary",
            },
            timeout=30.0,
        )
        assert response.status_code == 200
        assert captured.get("keep_alive") == "5m"
        assert captured.get("keep_alive") != -1
    finally:
        thread._server.shutdown()
        thread._server.server_close()
        thread.join(timeout=2.0)
