import time

from worker.fleet.config import FleetConfig
from worker.router.metrics import CallRecord, MetricsCollector


def test_batch_report_jobs_per_hour():
    fleet_cfg = FleetConfig(
        num_servers=2,
        parallel=2,
        max_slots=4,
        memory_tier="warm_stack",
        w_all_bytes=2 * 1024**3,
        w_peak_bytes=1 * 1024**3,
    )
    collector = MetricsCollector()
    collector.begin_batch()
    collector.record_call(
        model="gemma3:1b",
        role="gene_aggregation",
        backend="http://127.0.0.1:11434",
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
    assert report["per_model"]["gemma3:1b"]["inference_ms_total"] == 1000
    assert report["per_job"]["b1"]["wall_ms"] == 5000
    assert report["per_job"]["b1"]["stall_ms"] == 100
    assert report["efficiency"]["score"] > 0
    assert report["efficiency"]["components"]["lane_utilization"] >= 0


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
    assert report["efficiency"]["components"]["job_success_rate"] == 0.0


def test_per_model_peak_in_flight():
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
            backend="http://127.0.0.1:11434",
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
            backend="http://127.0.0.1:11434",
            queue_wait_ms=0,
            inference_ms=100,
            total_ms=1000,
            success=True,
        ),
    ]
    collector._batch_start = base
    collector.end_batch()
    report = collector.build_report(
        fleet_cfg=fleet_cfg,
        jobs_submitted=2,
        model_mode="nano",
    )
    assert report["per_model"]["gemma3:1b"]["peak_in_flight"] == 2
    assert report["per_backend"]["_fleet"]["peak_lane_usage"] == 2


def test_lane_utilization_reflects_idle_time():
    fleet_cfg = FleetConfig(num_servers=1, parallel=2, max_slots=2)
    collector = MetricsCollector()
    base = time.monotonic()
    collector.begin_batch()
    collector._batch_start = base
    # One short call on a 2-lane backend over ~2s window → low utilization.
    collector._calls = [
        CallRecord(
            ts=base + 0.1,
            job_id="j1",
            role="inference",
            model="gemma3:1b",
            backend="http://127.0.0.1:11434",
            queue_wait_ms=0,
            inference_ms=200,
            total_ms=200,
            success=True,
        ),
    ]
    collector._batch_end = base + 2.0
    report = collector.build_report(
        fleet_cfg=fleet_cfg,
        jobs_submitted=1,
        model_mode="nano",
    )
    backend = report["per_backend"]["http://127.0.0.1:11434"]
    assert backend["idle_lane_sec"] > backend["busy_lane_sec"]
    assert backend["lane_utilization"] < 0.2
    assert report["efficiency"]["derived"]["idle_lane_sec"] > 0


def test_efficiency_includes_memory_tier_component():
    fleet_cfg = FleetConfig(
        num_servers=1,
        parallel=1,
        max_slots=1,
        memory_tier="vram_overflow",
        w_all_bytes=52 * 1024**3,
        w_peak_bytes=16 * 1024**3,
    )
    collector = MetricsCollector()
    collector.begin_batch()
    collector.record_call(
        model="gemma3:27b",
        role="gene_aggregation",
        backend="http://127.0.0.1:11434",
        queue_wait_ms=0,
        inference_ms=500,
        total_ms=500,
        job_id="b1",
        success=True,
    )
    collector.record_job_done("b1", wall_ms=1000, failed=False)
    collector.end_batch()
    report = collector.build_report(
        fleet_cfg=fleet_cfg,
        jobs_submitted=1,
        model_mode="performance",
    )
    assert report["efficiency"]["components"]["memory_tier"] == 0.65
    assert report["fleet"]["memory_tier"] == "vram_overflow"
