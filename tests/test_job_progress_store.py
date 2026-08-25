from backend.job_store import JobStore


def test_mark_step_persists_structured_progress(tmp_path):
    store = JobStore(tmp_path / "jobs.sqlite3")
    job = store.create_job({"profile": "mtb-h37rv", "locus": "Rv0001"})
    store.mark_running(job["id"])
    store.mark_step(
        job["id"],
        "extracting 3/12 sections (target)",
        phase="extracting",
        sections_done=3,
        sections_total=12,
        pass_name="target",
    )
    got = store.get_job(job["id"])
    assert got["current_step"] == "extracting 3/12 sections (target)"
    assert got["progress_phase"] == "extracting"
    assert got["sections_done"] == 3
    assert got["sections_total"] == 12
    assert got["pass_name"] == "target"


def test_mark_step_without_structured_fields_clears_them(tmp_path):
    store = JobStore(tmp_path / "jobs.sqlite3")
    job = store.create_job({"profile": "mtb-h37rv", "locus": "Rv0001"})
    store.mark_running(job["id"])
    store.mark_step(
        job["id"],
        "extracting 3/12 sections (target)",
        phase="extracting",
        sections_done=3,
        sections_total=12,
        pass_name="target",
    )
    store.mark_step(job["id"], "queued")
    got = store.get_job(job["id"])
    assert got["current_step"] == "queued"
    assert got["progress_phase"] is None
    assert got["sections_done"] is None
    assert got["sections_total"] is None
    assert got["pass_name"] is None
