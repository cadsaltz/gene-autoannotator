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


def test_empty_claim_not_logged_while_jobs_active(caplog):
    import logging

    caplog.set_level(logging.INFO)
    source = CoordinatorJobSource(
        _FakeClient(),
        lambda: 1,
        active_jobs_fn=lambda: 1,
    )
    source.claim_one()
    assert not any("Idle: no job" in r.message for r in caplog.records)
