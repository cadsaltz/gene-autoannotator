import time

from worker.router.inflight import InflightTracker


def test_inflight_tracker_warns_on_stuck_call(caplog, monkeypatch):
    import logging

    caplog.set_level(logging.WARNING)
    start = time.monotonic()
    tracker = InflightTracker()

    def fake_monotonic():
        return start + 200

    monkeypatch.setattr(time, "monotonic", fake_monotonic)
    tracker.start(
        job_id="bench-001",
        model="qwen2.5:0.5b",
        role="section_summary",
        backend="http://127.0.0.1:11434",
    )
    tracker.maybe_warn_stuck(after_sec=120, interval_sec=0)
    assert any("Router Ollama call(s) still in flight" in r.message for r in caplog.records)


def test_inflight_snapshot_reports_elapsed(monkeypatch):
    start = time.monotonic()
    tracker = InflightTracker()
    times = [start, start + 45]

    def fake_monotonic():
        return times[min(len(times) - 1, 1)]

    monkeypatch.setattr(time, "monotonic", lambda: times[0])
    tracker.start(
        job_id="bench-002",
        model="qwen3:0.6b",
        role="section_summary",
        backend="http://127.0.0.1:11434",
    )
    times[0] = start + 45
    rows = tracker.snapshot()
    assert len(rows) == 1
    assert rows[0]["elapsed_sec"] == 45
