from worker import ollama_version


def test_assert_retries_while_server_is_starting(monkeypatch):
    calls = {"n": 0}

    def fake_fetch(host, timeout_sec=5.0):
        calls["n"] += 1
        if calls["n"] < 3:
            raise TimeoutError("timed out")
        return "0.33.1"

    monkeypatch.setenv("OLLAMA_REQUIRE_VERSION", "0.33.1")
    monkeypatch.setattr(ollama_version, "fetch_ollama_server_version", fake_fetch)
    monkeypatch.setattr(ollama_version.time, "sleep", lambda _s: None)

    assert ollama_version.assert_ollama_server_version("http://127.0.0.1:11434") == "0.33.1"
    assert calls["n"] == 3


def test_assert_gives_up_after_ready_timeout(monkeypatch):
    clock = {"t": 0.0}

    def fake_sleep(seconds):
        clock["t"] += seconds

    monkeypatch.setenv("OLLAMA_REQUIRE_VERSION", "0.33.1")
    monkeypatch.setattr(
        ollama_version,
        "fetch_ollama_server_version",
        lambda host, timeout_sec=5.0: (_ for _ in ()).throw(TimeoutError("timed out")),
    )
    monkeypatch.setattr(ollama_version.time, "sleep", fake_sleep)
    monkeypatch.setattr(ollama_version.time, "monotonic", lambda: clock["t"])
    monkeypatch.setattr(ollama_version, "VERSION_READY_TIMEOUT_SEC", 0.5)
    monkeypatch.setattr(ollama_version, "VERSION_POLL_INTERVAL_SEC", 0.5)

    try:
        ollama_version.assert_ollama_server_version("http://127.0.0.1:11434")
    except RuntimeError as exc:
        assert "timed out" in str(exc)
        assert "0.33.1" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")


def test_assert_skips_when_enforcement_disabled(monkeypatch):
    monkeypatch.setenv("OLLAMA_REQUIRE_VERSION", "off")
    assert ollama_version.assert_ollama_server_version("http://127.0.0.1:11434") is None
