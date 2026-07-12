import pytest

from worker.ollama_keep_alive import parse_ollama_keep_alive


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("-1", -1),
        ("forever", -1),
        ("infinite", -1),
        ("0", 0),
        ("5m", "5m"),
        ("300", 300),
        (None, None),
        ("", None),
    ],
)
def test_parse_ollama_keep_alive(raw, expected):
    assert parse_ollama_keep_alive(raw) == expected


def test_warm_all_models_calls_chat_for_each_required(monkeypatch):
    from worker import ollama_bootstrap

    chats = []

    class FakeClient:
        def chat(self, **kwargs):
            chats.append(kwargs)

    monkeypatch.setattr(
        ollama_bootstrap,
        "required_models",
        lambda: ["qwen3:0.6b", "qwen2.5:0.5b"],
    )
    warmed = ollama_bootstrap.warm_all_models(client=FakeClient(), keep_alive=-1)
    assert warmed == ["qwen2.5:0.5b", "qwen3:0.6b"]
    assert len(chats) == 2
    assert all(call["keep_alive"] == -1 for call in chats)


def test_ollama_chat_passes_keep_alive_forever(monkeypatch):
    from autoannotation import llms

    captured = {}

    class FakeRouter:
        def chat(self, **kwargs):
            captured.update(kwargs)
            return {
                "message": {"content": "{}"},
                "total_duration": 1_000_000_000,
            }

    monkeypatch.setenv("AUTOANNOTATION_OLLAMA_KEEP_ALIVE", "forever")
    monkeypatch.setenv("OLLAMA_ROUTER_URL", "http://127.0.0.1:11499")
    monkeypatch.setattr("worker.router.client.RouterClient", lambda url: FakeRouter())
    llms.ollama_chat(
        model="fake-model",
        messages=[{"role": "user", "content": "hi"}],
        role="test",
    )
    assert captured["keep_alive"] == -1
