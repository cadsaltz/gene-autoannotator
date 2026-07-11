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
