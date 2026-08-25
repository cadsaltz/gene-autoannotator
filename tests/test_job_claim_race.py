import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from fastapi.testclient import TestClient

from coordinator.annotation_store import InMemoryAnnotationStore
from coordinator.api import create_app
from coordinator.job_store import JobStore


def test_two_claimers_only_one_wins(tmp_path):
    store = JobStore(tmp_path / "jobs.sqlite3")
    job = store.create_job({"profile": "mtb-h37rv", "locus": "Rv0001"})
    claim_barrier = Barrier(2)

    def synchronized_claim(worker_id):
        claim_barrier.wait(timeout=5)
        return store.assign_job_to_worker(worker_id, lease_seconds=60)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(synchronized_claim, worker_id)
            for worker_id in ("serve-a", "run-b")
        ]
        results = [future.result() for future in futures]

    won = [result for result in results if result is not None]
    assert len(won) == 1
    assert store.get_job(job["id"])["status"] == "running"


def test_assign_job_returns_none_when_guarded_update_loses_race(tmp_path):
    db_path = tmp_path / "jobs.sqlite3"
    store = JobStore(db_path)
    job = store.create_job({"profile": "mtb-h37rv", "locus": "Rv0001"})

    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            CREATE TRIGGER lose_claim_before_update
            BEFORE UPDATE ON annotation_jobs
            WHEN OLD.status = 'queued' AND NEW.status = 'running'
            BEGIN
                SELECT RAISE(IGNORE);
            END
            """
        )

    assert store.assign_job_to_worker("worker-a", lease_seconds=60) is None
    assert store.get_job(job["id"])["status"] == "queued"


def test_count_queued_jobs_does_not_claim(tmp_path):
    store = JobStore(tmp_path / "jobs.sqlite3")
    claimed_job = store.create_job({"profile": "mtb-h37rv", "locus": "Rv0001"})
    remaining_job = store.create_job({"profile": "mtb-h37rv", "locus": "Rv0002"})
    store.assign_job_to_worker("worker-a", lease_seconds=60)

    assert store.count_queued_jobs() == 1
    assert store.get_job(claimed_job["id"])["status"] == "running"
    assert store.get_job(remaining_job["id"])["status"] == "queued"


def test_queue_summary_endpoint_peeks_without_claiming(tmp_path):
    store = JobStore(tmp_path / "jobs.sqlite3")
    job = store.create_job({"profile": "mtb-h37rv", "locus": "Rv0001"})
    app = create_app(
        job_store=store,
        annotation_store=InMemoryAnnotationStore(),
        start_worker=False,
    )

    response = TestClient(app).get("/jobs/queue-summary")

    assert response.status_code == 200
    assert response.json() == {"queued": 1}
    assert store.get_job(job["id"])["status"] == "queued"
