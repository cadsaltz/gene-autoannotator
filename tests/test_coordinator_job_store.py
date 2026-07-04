from coordinator.job_store import JobStore


def test_creates_and_fetches_queued_job(tmp_path):
    store = JobStore(tmp_path / "jobs.sqlite3")
    request = {
        "profile": "tcruzi-clbrener",
        "organism": None,
        "strain": None,
        "locus": "TcCLB.503799.4",
        "name": None,
        "cache_dir": "./.cache",
        "output_dir": "gen_json",
        "allow_online_name_lookup": False,
        "refresh_gene_name_cache": False,
        "cache_supplied_name": False,
    }

    created = store.create_job(request)
    fetched = store.get_job(created["id"])

    assert created["status"] == "queued"
    assert fetched["id"] == created["id"]
    assert fetched["request"] == request
    assert fetched["result"] is None
    assert fetched["error"] is None
    assert fetched["created_at"] is not None
    assert fetched["started_at"] is None
    assert fetched["finished_at"] is None


def test_tracks_running_and_completed_job(tmp_path):
    store = JobStore(tmp_path / "jobs.sqlite3")
    created = store.create_job({"profile": "mtb-h37rv", "locus": "Rv0001"})
    result = {
        "annotation": {"gene_id": "Rv0001", "name": "dnaA"},
        "papers_used": ["123"],
        "all_papers": ["123", "456"],
        "output_path": "gen_json/gen_Rv0001.json",
        "cumulative_relevance": 0.9,
        "selection_mode": "target_relevance_reached",
    }

    store.mark_running(created["id"])
    running = store.get_job(created["id"])
    store.mark_completed(created["id"], result, output_path=result["output_path"])
    completed = store.get_job(created["id"])

    assert running["status"] == "running"
    assert running["started_at"] is not None
    assert completed["status"] == "completed"
    assert completed["result"] == result
    assert completed["output_path"] == "gen_json/gen_Rv0001.json"
    assert completed["finished_at"] is not None


def test_tracks_failed_job_error(tmp_path):
    store = JobStore(tmp_path / "jobs.sqlite3")
    created = store.create_job({"profile": "mtb-h37rv", "locus": "bad"})

    store.mark_running(created["id"])
    store.mark_failed(created["id"], "Invalid locus")
    failed = store.get_job(created["id"])

    assert failed["status"] == "failed"
    assert failed["error"] == "Invalid locus"
    assert failed["finished_at"] is not None


def test_lists_jobs_with_queue_positions(tmp_path):
    store = JobStore(tmp_path / "jobs.sqlite3")
    running = store.create_job({"profile": "mtb-h37rv", "locus": "Rv0001"})
    queued_first = store.create_job({"profile": "mtb-h37rv", "locus": "Rv0002"})
    queued_second = store.create_job({"profile": "mtb-h37rv", "locus": "Rv0003"})

    store.mark_running(running["id"])

    jobs = store.list_jobs(order="queue")
    jobs_by_id = {job["id"]: job for job in jobs}

    assert [job["id"] for job in jobs] == [
        running["id"],
        queued_first["id"],
        queued_second["id"],
    ]
    assert jobs_by_id[running["id"]]["queue_position"] is None
    assert jobs_by_id[running["id"]]["current_step"] == "running"
    assert jobs_by_id[queued_first["id"]]["queue_position"] == 1
    assert jobs_by_id[queued_second["id"]]["queue_position"] == 2


def test_claim_next_queued_job_allows_second_when_first_running(tmp_path):
    store = JobStore(tmp_path / "jobs.sqlite3")
    j1 = store.create_job({"profile": "mtb-h37rv", "locus": "Rv0001"})
    j2 = store.create_job({"profile": "mtb-h37rv", "locus": "Rv0002"})
    store.mark_running(j1["id"])
    claimed = store.claim_next_queued_job()
    assert claimed is not None
    assert claimed["id"] == j2["id"]


def test_marks_interrupted_running_jobs_failed_on_restart(tmp_path):
    store = JobStore(tmp_path / "jobs.sqlite3")
    running = store.create_job({"profile": "mtb-h37rv", "locus": "Rv0001"})
    queued = store.create_job({"profile": "mtb-h37rv", "locus": "Rv0002"})

    store.mark_running(running["id"])
    interrupted_count = store.mark_interrupted_running_jobs("API restarted")
    claimed = store.claim_next_queued_job()
    failed = store.get_job(running["id"])

    assert interrupted_count == 1
    assert failed["status"] == "failed"
    assert failed["error"] == "API restarted"
    assert claimed["id"] == queued["id"]


def test_clear_finished_jobs_keeps_running_and_queued_jobs(tmp_path):
    store = JobStore(tmp_path / "jobs.sqlite3")
    completed = store.create_job({"profile": "mtb-h37rv", "locus": "Rv0001"})
    failed = store.create_job({"profile": "mtb-h37rv", "locus": "Rv0002"})
    queued = store.create_job({"profile": "mtb-h37rv", "locus": "Rv0003"})
    running = store.create_job({"profile": "mtb-h37rv", "locus": "Rv0004"})

    store.mark_completed(completed["id"], {"annotation": {"gene_id": "Rv0001"}})
    store.mark_failed(failed["id"], "bad paper")
    store.mark_running(running["id"])

    deleted_count = store.clear_finished_jobs()
    remaining_ids = {job["id"] for job in store.list_jobs(order="queue")}

    assert deleted_count == 2
    assert remaining_ids == {queued["id"], running["id"]}


def test_new_job_has_worker_and_lease_defaults(tmp_path):
    store = JobStore(tmp_path / "jobs.sqlite3")
    job = store.create_job(
        {"profile": "mtb-h37rv", "locus": "Rv0001", "cache_dir": "./.cache", "output_dir": "gen_json"}
    )
    assert job["worker_id"] is None
    assert job["lease_expires_at"] is None
    assert job["attempts"] == 0


def _queued(store, locus):
    return store.create_job(
        {"profile": "mtb-h37rv", "locus": locus, "cache_dir": "./.cache", "output_dir": "gen_json"}
    )


def test_two_workers_get_different_jobs(tmp_path):
    store = JobStore(tmp_path / "jobs.sqlite3")
    _queued(store, "Rv0001")
    _queued(store, "Rv0002")
    first = store.assign_job_to_worker("worker-a", lease_seconds=3600)
    second = store.assign_job_to_worker("worker-b", lease_seconds=3600)
    assert first["id"] != second["id"]
    assert first["worker_id"] == "worker-a"
    assert second["worker_id"] == "worker-b"
    assert store.assign_job_to_worker("worker-c", lease_seconds=3600) is None


def test_no_global_running_cap(tmp_path):
    store = JobStore(tmp_path / "jobs.sqlite3")
    _queued(store, "Rv0001")
    _queued(store, "Rv0002")
    store.assign_job_to_worker("worker-a", lease_seconds=3600)
    # A second assignment succeeds even though one job is already running.
    assert store.assign_job_to_worker("worker-b", lease_seconds=3600) is not None


def test_expired_lease_requeues_then_fails(tmp_path):
    store = JobStore(tmp_path / "jobs.sqlite3")
    job = _queued(store, "Rv0001")
    store.assign_job_to_worker("worker-a", lease_seconds=-1)  # already expired
    result = store.requeue_expired_leases(max_attempts=3)
    assert job["id"] in result["requeued"]
    assert store.get_job(job["id"])["status"] == "queued"


def test_lease_fails_after_max_attempts(tmp_path):
    store = JobStore(tmp_path / "jobs.sqlite3")
    job = _queued(store, "Rv0001")
    result = {"requeued": [], "failed": []}
    for _ in range(3):
        store.assign_job_to_worker("worker-a", lease_seconds=-1)
        result = store.requeue_expired_leases(max_attempts=3)
    assert job["id"] in result["failed"]
    assert store.get_job(job["id"])["status"] == "failed"


def test_complete_if_running_is_idempotent(tmp_path):
    store = JobStore(tmp_path / "jobs.sqlite3")
    job = _queued(store, "Rv0001")
    store.assign_job_to_worker("worker-a", lease_seconds=3600)
    assert store.complete_if_running(job["id"], {"annotation": {"gene_id": "Rv0001"}}) is True
    assert store.complete_if_running(job["id"], {"annotation": {"gene_id": "X"}}) is False
    assert store.get_job(job["id"])["result"]["annotation"]["gene_id"] == "Rv0001"


def test_fail_job_requeues_when_retryable(tmp_path):
    store = JobStore(tmp_path / "jobs.sqlite3")
    job = _queued(store, "Rv0001")
    store.assign_job_to_worker("worker-a", lease_seconds=3600)
    store.fail_job(job["id"], "ollama down", retryable=True, max_attempts=3)
    assert store.get_job(job["id"])["status"] == "queued"
    store.assign_job_to_worker("worker-a", lease_seconds=3600)
    store.fail_job(job["id"], "bad locus", retryable=False, max_attempts=3)
    assert store.get_job(job["id"])["status"] == "failed"


def test_complete_if_running_ignores_non_running_job(tmp_path):
    store = JobStore(tmp_path / "jobs.sqlite3")
    job = _queued(store, "Rv0001")
    # Job is queued, not running: completion must be refused and status preserved.
    assert store.complete_if_running(job["id"], {"annotation": {"gene_id": "Rv0001"}}) is False
    assert store.get_job(job["id"])["status"] == "queued"


def test_complete_if_running_refuses_after_requeue(tmp_path):
    store = JobStore(tmp_path / "jobs.sqlite3")
    job = _queued(store, "Rv0001")
    store.assign_job_to_worker("worker-a", lease_seconds=-1)  # expired lease
    store.requeue_expired_leases(max_attempts=3)  # back to queued
    # A stale worker that lost its lease must not be able to complete the job.
    assert store.complete_if_running(job["id"], {"annotation": {}}) is False
    assert store.get_job(job["id"])["status"] == "queued"
