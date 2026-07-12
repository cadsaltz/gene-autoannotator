from worker.router.timeouts import (
    DEFAULT_CHAT_TIMEOUT_SEC,
    ollama_chat_timeout,
    ollama_chat_timeout_for_role,
    router_http_timeout,
)


def test_role_timeout_defaults(monkeypatch):
    monkeypatch.delenv("OLLAMA_CHAT_TIMEOUT_SEC", raising=False)
    assert ollama_chat_timeout_for_role("section_summary") == 120.0
    assert ollama_chat_timeout_for_role("section_consensus") == 180.0
    assert ollama_chat_timeout_for_role("gene_aggregation") == 600.0
    assert ollama_chat_timeout_for_role("unknown_role") == DEFAULT_CHAT_TIMEOUT_SEC


def test_global_timeout_overrides_role(monkeypatch):
    monkeypatch.setenv("OLLAMA_CHAT_TIMEOUT_SEC", "90")
    assert ollama_chat_timeout_for_role("gene_aggregation") == 90.0


def test_unlimited_global_still_uses_role_defaults(monkeypatch):
    monkeypatch.setenv("OLLAMA_CHAT_TIMEOUT_SEC", "0")
    assert ollama_chat_timeout_for_role("section_summary") == 120.0
    assert ollama_chat_timeout() is None


def test_router_http_timeout_has_finite_read_by_default(monkeypatch):
    monkeypatch.delenv("OLLAMA_ROUTER_READ_TIMEOUT_SEC", raising=False)
    monkeypatch.delenv("OLLAMA_CHAT_TIMEOUT_SEC", raising=False)
    timeout = router_http_timeout()
    assert timeout.read is not None
    assert timeout.read >= 600.0


def test_router_http_timeout_respects_explicit_read(monkeypatch):
    monkeypatch.setenv("OLLAMA_ROUTER_READ_TIMEOUT_SEC", "120")
    timeout = router_http_timeout()
    assert timeout.read == 120.0
