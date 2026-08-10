import pytest
import requests
from urllib3.exceptions import ProtocolError

from autoannotation import http_


def test_throttler_retries_transient_protocol_error(monkeypatch):
    monkeypatch.setenv("AUTOANNOTATION_HTTP_GET_ATTEMPTS", "3")
    monkeypatch.setenv("AUTOANNOTATION_HTTP_RETRY_BACKOFF_SEC", "0")

    calls = {"count": 0}

    class FakeResponse:
        status_code = 200
        text = "ok"

    def flaky_request():
        calls["count"] += 1
        if calls["count"] < 3:
            raise ProtocolError("Response ended prematurely")
        return FakeResponse()

    throttler = http_.Throttler(cooldown_secs=0.001, timeout_secs=1)
    response = throttler.throttle("example.test", flaky_request)
    assert response.text == "ok"
    assert calls["count"] == 3


def test_throttler_does_not_retry_non_transient_errors(monkeypatch):
    monkeypatch.setenv("AUTOANNOTATION_HTTP_GET_ATTEMPTS", "3")
    monkeypatch.setenv("AUTOANNOTATION_HTTP_RETRY_BACKOFF_SEC", "0")

    calls = {"count": 0}

    def bad_request():
        calls["count"] += 1
        raise ValueError("bad url")

    throttler = http_.Throttler(cooldown_secs=0.001, timeout_secs=1)
    with pytest.raises(ValueError, match="bad url"):
        throttler.throttle("example.test", bad_request)
    assert calls["count"] == 1


def test_throttler_retries_retryable_http_status(monkeypatch):
    monkeypatch.setenv("AUTOANNOTATION_HTTP_GET_ATTEMPTS", "2")
    monkeypatch.setenv("AUTOANNOTATION_HTTP_RETRY_BACKOFF_SEC", "0")

    calls = {"count": 0}

    class RateLimitedResponse:
        def __init__(self, status_code):
            self.status_code = status_code
            self.text = "ok"

        def raise_for_status(self):
            raise requests.exceptions.HTTPError(response=self)

    def flaky_request():
        calls["count"] += 1
        if calls["count"] == 1:
            return RateLimitedResponse(503)
        return RateLimitedResponse(200)

    throttler = http_.Throttler(cooldown_secs=0.001, timeout_secs=1)
    response = throttler.throttle("example.test", flaky_request)
    assert response.status_code == 200
    assert calls["count"] == 2


def test_throttler_retries_empty_response_body(monkeypatch):
    monkeypatch.setenv("AUTOANNOTATION_HTTP_GET_ATTEMPTS", "3")
    monkeypatch.setenv("AUTOANNOTATION_HTTP_RETRY_BACKOFF_SEC", "0")

    calls = {"count": 0}

    class FakeResponse:
        def __init__(self, text):
            self.status_code = 200
            self.text = text

    def flaky_request():
        calls["count"] += 1
        if calls["count"] < 3:
            return FakeResponse("")
        return FakeResponse('{"ok": true}')

    throttler = http_.Throttler(cooldown_secs=0.001, timeout_secs=1)
    response = throttler.throttle("eutils.ncbi.nlm.nih.gov", flaky_request)
    assert response.text == '{"ok": true}'
    assert calls["count"] == 3


def test_throttler_raises_after_empty_body_retries_exhausted(monkeypatch):
    monkeypatch.setenv("AUTOANNOTATION_HTTP_GET_ATTEMPTS", "2")
    monkeypatch.setenv("AUTOANNOTATION_HTTP_RETRY_BACKOFF_SEC", "0")

    class EmptyResponse:
        status_code = 200
        text = "   "

    def always_empty():
        return EmptyResponse()

    throttler = http_.Throttler(cooldown_secs=0.001, timeout_secs=1)
    with pytest.raises(requests.exceptions.HTTPError, match="empty body"):
        throttler.throttle("eutils.ncbi.nlm.nih.gov", always_empty)


def test_throttler_cooldown_env_override(monkeypatch):
    monkeypatch.setenv("AUTOANNOTATION_HTTP_COOLDOWN_SEC", "1.25")
    throttler = http_.Throttler()
    assert throttler.cooldown_seconds == 1.25
