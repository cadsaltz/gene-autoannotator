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


def test_claim_next_queued_job_respects_single_running_job(tmp_path):
    store = JobStore(tmp_path / "jobs.sqlite3")
    first = store.create_job({"profile": "mtb-h37rv", "locus": "Rv0001"})
    second = store.create_job({"profile": "mtb-h37rv", "locus": "Rv0002"})

    claimed = store.claim_next_queued_job()
    blocked = store.claim_next_queued_job()
    store.mark_completed(claimed["id"], {"annotation": {"gene_id": "Rv0001"}})
    next_claimed = store.claim_next_queued_job()

    assert claimed["id"] == first["id"]
    assert claimed["status"] == "running"
    assert blocked is None
    assert next_claimed["id"] == second["id"]
    assert next_claimed["status"] == "running"


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
