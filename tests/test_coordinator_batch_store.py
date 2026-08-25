from backend.batch_store import BatchStore
from backend.job_store import JobStore


def test_creates_and_fetches_batch(tmp_path):
    db_path = tmp_path / "jobs.sqlite3"
    store = BatchStore(db_path)

    created = store.create_batch(
        profile="mtb-h37rv",
        options={"allow_online_name_lookup": False},
        input_summary={"total": 3, "ready": 3, "ambiguous": 0, "invalid": 0, "duplicate_skipped": 0},
    )
    fetched = store.get_batch(created["id"])

    assert created["status"] == "queued"
    assert created["profile"] == "mtb-h37rv"
    assert created["organism"] is None
    assert created["strain"] is None
    assert created["options"] == {"allow_online_name_lookup": False}
    assert created["input_summary"]["ready"] == 3
    assert created["created_at"] is not None
    assert fetched == created


def test_links_jobs_to_batch(tmp_path):
    db_path = tmp_path / "jobs.sqlite3"
    batch_store = BatchStore(db_path)
    job_store = JobStore(db_path)

    batch = batch_store.create_batch(
        profile="mtb-h37rv",
        input_summary={"total": 2, "ready": 2, "ambiguous": 0, "invalid": 0, "duplicate_skipped": 0},
    )
    first = job_store.create_job({"profile": "mtb-h37rv", "locus": "Rv0001"}, batch_id=batch["id"])
    second = job_store.create_job({"profile": "mtb-h37rv", "locus": "Rv0002"}, batch_id=batch["id"])
    standalone = job_store.create_job({"profile": "mtb-h37rv", "locus": "Rv0003"})

    assert first["batch_id"] == batch["id"]
    assert second["batch_id"] == batch["id"]
    assert standalone["batch_id"] is None


def test_list_jobs_by_batch(tmp_path):
    db_path = tmp_path / "jobs.sqlite3"
    batch_store = BatchStore(db_path)
    job_store = JobStore(db_path)

    batch = batch_store.create_batch(
        profile="mtb-h37rv",
        input_summary={"total": 2, "ready": 2, "ambiguous": 0, "invalid": 0, "duplicate_skipped": 0},
    )
    first = job_store.create_job({"profile": "mtb-h37rv", "locus": "Rv0001"}, batch_id=batch["id"])
    second = job_store.create_job({"profile": "mtb-h37rv", "locus": "Rv0002"}, batch_id=batch["id"])
    job_store.create_job({"profile": "mtb-h37rv", "locus": "Rv0003"})

    by_batch = job_store.list_jobs_by_batch(batch["id"])
    filtered = job_store.list_jobs(batch_id=batch["id"], order="newest", limit=10)

    assert [job["id"] for job in by_batch] == [first["id"], second["id"]]
    assert {job["id"] for job in filtered} == {first["id"], second["id"]}
    assert all(job["batch_id"] == batch["id"] for job in by_batch)
