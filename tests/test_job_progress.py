from shared.job_progress import JobProgressEvent, format_current_step
from shared.worker_contract import JobProgress


def test_format_current_step_extracting():
    event = JobProgressEvent(
        phase="extracting",
        sections_done=3,
        sections_total=18,
        pass_name="target",
    )
    assert format_current_step(event) == "extracting 3/18 sections (target)"


def test_format_current_step_fetching_unknown_total():
    event = JobProgressEvent(phase="fetching", sections_done=0, sections_total=None)
    assert "fetching" in format_current_step(event)
    assert "?" in format_current_step(event)


def test_job_progress_accepts_structured_fields():
    payload = JobProgress(
        current_step="extracting 1/2 sections (target)",
        phase="extracting",
        sections_done=1,
        sections_total=2,
        pass_name="target",
    )
    assert payload.sections_done == 1
