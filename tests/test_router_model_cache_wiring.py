import pytest

from worker.router import server as router_server


def test_cache_ensure_release_around_chat():
    events = []

    class DummyCache:
        def ensure(self, model):
            events.append(("ensure", model))

        def release(self, model):
            events.append(("release", model))

    def chat_fn():
        events.append(("chat",))
        return {"message": {"content": "ok"}}

    result = router_server._run_cached_chat(DummyCache(), "qwen3:8b", chat_fn)

    assert result["message"]["content"] == "ok"
    assert events == [
        ("ensure", "qwen3:8b"),
        ("chat",),
        ("release", "qwen3:8b"),
    ]


def test_cache_releases_model_when_chat_fails():
    events = []

    class DummyCache:
        def ensure(self, model):
            events.append(("ensure", model))

        def release(self, model):
            events.append(("release", model))

    def chat_fn():
        events.append(("chat",))
        raise RuntimeError("chat failed")

    with pytest.raises(RuntimeError, match="chat failed"):
        router_server._run_cached_chat(DummyCache(), "qwen3:8b", chat_fn)

    assert events == [
        ("ensure", "qwen3:8b"),
        ("chat",),
        ("release", "qwen3:8b"),
    ]
