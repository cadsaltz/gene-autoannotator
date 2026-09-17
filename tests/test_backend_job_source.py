import time

from worker.sources.backend import BackendJobSource


class _FakeClient:
    def claim(self, free_slots):
        return None


def test_backend_wait_or_sleep_uses_poll_interval(monkeypatch):
    monkeypatch.setenv("WORKER_CLAIM_POLL_SECONDS", "0.25")
    source = BackendJobSource(_FakeClient(), lambda: 1, poll_seconds=None)
    started = time.monotonic()
    source.wait_or_sleep(timeout=0.1)
    elapsed = time.monotonic() - started
    assert elapsed >= 0.24


def test_empty_claim_not_logged_while_jobs_active(caplog):
    import logging

    caplog.set_level(logging.INFO)
    source = BackendJobSource(
        _FakeClient(),
        lambda: 1,
        active_jobs_fn=lambda: 1,
    )
    source.claim_one()
    assert not any("Idle: no job" in r.message for r in caplog.records)
