import time

from worker.fleet.config import FleetConfig
from worker.router.metrics import MetricsCollector


def test_batch_report_jobs_per_hour():
    fleet_cfg = FleetConfig(num_servers=2, parallel=2, max_slots=4)
    collector = MetricsCollector()
    collector.begin_batch()
    collector.record_call(
        model="gemma3:1b",
        role="gene_aggregation",
        backend="h1",
        queue_wait_ms=100,
        inference_ms=1000,
        total_ms=1100,
        job_id="b1",
        success=True,
    )
    collector.record_job_done("b1", wall_ms=5000, failed=False)
    time.sleep(0.05)
    collector.end_batch()
    report = collector.build_report(
        fleet_cfg=fleet_cfg,
        jobs_submitted=1,
        model_mode="nano",
    )
    assert report["batch"]["jobs_completed"] == 1
    assert report["primary_kpi"] == "jobs_per_hour"
    assert report["batch"]["jobs_per_hour"] > 0
    assert report["fleet"]["num_servers"] == 2
    assert report["fleet"]["lanes"] == 4
    assert report["fleet"]["model_mode"] == "nano"
    assert report["per_model"]["gemma3:1b"]["calls"] == 1
    assert report["per_model"]["gemma3:1b"]["p50_queue_wait_ms"] == 100
    assert report["per_job"]["b1"]["wall_ms"] == 5000
    assert report["per_job"]["b1"]["stall_ms"] == 100


def test_batch_report_tracks_failed_jobs():
    fleet_cfg = FleetConfig(num_servers=1, parallel=1, max_slots=1)
    collector = MetricsCollector()
    collector.begin_batch()
    collector.record_job_done("b1", wall_ms=1000, failed=True)
    collector.end_batch()
    report = collector.build_report(
        fleet_cfg=fleet_cfg,
        jobs_submitted=1,
        model_mode="nano",
    )
    assert report["batch"]["jobs_completed"] == 0
    assert report["batch"]["jobs_failed"] == 1


def test_per_model_peak_in_flight():
    from worker.router.metrics import CallRecord

    fleet_cfg = FleetConfig(num_servers=1, parallel=2, max_slots=2)
    collector = MetricsCollector()
    collector.begin_batch()
    base = time.monotonic()
    collector._calls = [
        CallRecord(
            ts=base,
            job_id="j1",
            role="inference",
            model="gemma3:1b",
            backend="h1",
            queue_wait_ms=0,
            inference_ms=100,
            total_ms=1000,
            success=True,
        ),
        CallRecord(
            ts=base + 0.1,
            job_id="j2",
            role="inference",
            model="gemma3:1b",
            backend="h1",
            queue_wait_ms=0,
            inference_ms=100,
            total_ms=1000,
            success=True,
        ),
    ]
    collector.end_batch()
    report = collector.build_report(
        fleet_cfg=fleet_cfg,
        jobs_submitted=2,
        model_mode="nano",
    )
    assert report["per_model"]["gemma3:1b"]["peak_in_flight"] == 2
