import os

from worker.router.timeouts import (
    ensure_router_read_timeout_for_load,
    ollama_chat_timeout,
    router_http_timeout,
    router_read_timeout_for_load,
)


def test_llm_read_timeouts_unlimited_by_default(monkeypatch):
    monkeypatch.delenv("OLLAMA_ROUTER_READ_TIMEOUT_SEC", raising=False)
    monkeypatch.delenv("OLLAMA_CHAT_TIMEOUT_SEC", raising=False)
    assert ollama_chat_timeout() is None
    timeout = router_http_timeout()
    assert timeout.read is None
    assert timeout.connect == 30.0


def test_llm_read_timeout_env_zero_means_unlimited(monkeypatch):
    monkeypatch.setenv("OLLAMA_ROUTER_READ_TIMEOUT_SEC", "0")
    monkeypatch.setenv("OLLAMA_CHAT_TIMEOUT_SEC", "none")
    assert ollama_chat_timeout() is None
    assert router_http_timeout().read is None


def test_llm_read_timeout_env_sets_finite_value(monkeypatch):
    monkeypatch.setenv("OLLAMA_ROUTER_READ_TIMEOUT_SEC", "7200")
    monkeypatch.setenv("OLLAMA_CHAT_TIMEOUT_SEC", "3600")
    assert ollama_chat_timeout() == 3600.0
    assert router_http_timeout().read == 7200.0


def test_router_read_timeout_scales_only_when_configured(monkeypatch):
    monkeypatch.delenv("OLLAMA_ROUTER_READ_TIMEOUT_SEC", raising=False)
    assert router_read_timeout_for_load(slots=4, lanes=1) is None

    monkeypatch.setenv("OLLAMA_ROUTER_READ_TIMEOUT_SEC", "600")
    assert router_read_timeout_for_load(slots=4, lanes=1) == 2430.0
    assert router_read_timeout_for_load(slots=2, lanes=2) == 630.0


def test_ensure_router_read_timeout_leaves_env_unset_by_default(monkeypatch):
    monkeypatch.delenv("OLLAMA_ROUTER_READ_TIMEOUT_SEC", raising=False)
    assert ensure_router_read_timeout_for_load(slots=6, lanes=1) is None
    assert "OLLAMA_ROUTER_READ_TIMEOUT_SEC" not in os.environ


def test_ensure_router_read_timeout_scales_finite_env(monkeypatch):
    monkeypatch.setenv("OLLAMA_ROUTER_READ_TIMEOUT_SEC", "600")
    timeout = ensure_router_read_timeout_for_load(slots=6, lanes=1)
    assert timeout == 3630.0
    assert os.environ["OLLAMA_ROUTER_READ_TIMEOUT_SEC"] == "3630"
