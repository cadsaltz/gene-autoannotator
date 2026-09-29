import time

import httpx

from worker.client import BackendClient


class _Config:
    backend_url = "http://backend.test"
    worker_api_token = "tok"
    worker_name = "w"
    hostname = "h"
    agent_version = "test"
    total_memory_bytes = 1
    dedicated_memory_bytes = 1
    max_slots = 1


class _FlakyHttp:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0

    def post(self, path, headers=None, json=None):
        del headers, json
        self.calls += 1
        item = self._responses.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


class _FlakyPatchHttp(_FlakyHttp):
    def patch(self, path, headers=None, json=None):
        return self.post(path, headers=headers, json=json)


def test_progress_keeps_short_retry_budget(monkeypatch):
    monkeypatch.setenv("WORKER_COMPLETE_RETRY_SECONDS", "300")
    monkeypatch.setattr(time, "sleep", lambda _s: None)
    http = _FlakyPatchHttp([httpx.ConnectError("down")] * 5)
    client = BackendClient(_Config(), http_client=http)

    try:
        client.progress("j1", "step")
        raise AssertionError("expected ConnectError")
    except httpx.ConnectError:
        pass
    assert http.calls == 4


def test_complete_outlasts_short_retry_budget(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda _s: None)
    ok = httpx.Response(204, request=httpx.Request("POST", "http://backend.test/jobs/j1/complete"))
    http = _FlakyHttp([httpx.RemoteProtocolError("Server disconnected")] * 6 + [ok])
    client = BackendClient(_Config(), http_client=http)

    client.complete("j1", {"ok": True})

    assert http.calls == 7


def test_claim_retries_transient_disconnect_then_succeeds(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda _s: None)
    ok = httpx.Response(204, request=httpx.Request("POST", "http://backend.test/claim"))
    http = _FlakyHttp(
        [
            httpx.RemoteProtocolError("Server disconnected without sending a response."),
            ok,
        ]
    )
    client = BackendClient(_Config(), http_client=http)
    client.worker_id = "w1"

    assert client.claim(free_slots=1) is None
    assert http.calls == 2


def test_claim_raises_after_retries_exhausted(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda _s: None)
    http = _FlakyHttp(
        [
            httpx.RemoteProtocolError("Server disconnected without sending a response."),
            httpx.RemoteProtocolError("Server disconnected without sending a response."),
            httpx.RemoteProtocolError("Server disconnected without sending a response."),
            httpx.RemoteProtocolError("Server disconnected without sending a response."),
        ]
    )
    client = BackendClient(_Config(), http_client=http)
    client.worker_id = "w1"

    try:
        client.claim(free_slots=1)
        raise AssertionError("expected RemoteProtocolError")
    except httpx.RemoteProtocolError:
        pass
    assert http.calls == 4
