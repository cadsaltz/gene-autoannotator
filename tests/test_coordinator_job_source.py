import time

from worker.sources.coordinator import CoordinatorJobSource


class _FakeClient:
    def claim(self, free_slots):
        return None


def test_coordinator_wait_or_sleep_uses_poll_interval(monkeypatch):
    monkeypatch.setenv("WORKER_CLAIM_POLL_SECONDS", "0.25")
    source = CoordinatorJobSource(_FakeClient(), lambda: 1, poll_seconds=None)
    started = time.monotonic()
    source.wait_or_sleep(timeout=0.1)
    elapsed = time.monotonic() - started
    assert elapsed >= 0.24
