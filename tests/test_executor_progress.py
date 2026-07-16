"""Tests for subprocess stderr NDJSON progress transport."""

import io
import json

from shared.job_progress import JobProgressEvent
from worker.executor import parse_progress_stderr_line


def test_parse_progress_stderr_line_valid():
    line = '{"type":"progress","phase":"extracting","sections_done":1,"sections_total":4,"pass_name":"target"}'
    event = parse_progress_stderr_line(line)
    assert event is not None
    assert event.sections_done == 1


def test_parse_progress_stderr_line_ignores_noise():
    assert parse_progress_stderr_line("I | Starting annotation") is None


def test_parse_progress_stderr_line_ignores_non_progress_json():
    assert parse_progress_stderr_line('{"type":"log","message":"hi"}') is None


def test_parse_progress_stderr_line_ignores_blank():
    assert parse_progress_stderr_line("") is None
    assert parse_progress_stderr_line("   ") is None


def test_parse_progress_stderr_line_ignores_invalid_event_fields():
    # Valid JSON, marked as progress, but fails JobProgressEvent validation
    # (missing required `phase`).
    assert parse_progress_stderr_line('{"type":"progress","sections_done":1}') is None


def test_parse_progress_stderr_line_ignores_json_array():
    assert parse_progress_stderr_line("[1, 2, 3]") is None


def test_run_subprocess_streams_progress_and_keeps_stdout_clean(monkeypatch):
    from worker import executor

    monkeypatch.setenv("WORKER_JOB_EXECUTION", "subprocess")

    progress_lines = [
        json.dumps({"type": "progress", "phase": "fetching", "sections_done": 0}),
        "I | some annotation log noise",
        json.dumps(
            {
                "type": "progress",
                "phase": "extracting",
                "sections_done": 1,
                "sections_total": 2,
                "pass_name": "target",
            }
        ),
    ]
    result_payload = {"annotation": {"gene_id": "Rv0001"}, "output_path": "gen_json/gen_Rv0001.json"}

    class FakePopen:
        def __init__(self, cmd, **kwargs):
            self.stdout = io.StringIO(json.dumps(result_payload))
            self.stderr = io.StringIO("\n".join(progress_lines) + "\n")
            self.returncode = None

        def wait(self, timeout=None):
            self.returncode = 0
            return self.returncode

        def terminate(self):
            pass

        def kill(self):
            pass

    monkeypatch.setattr(executor.subprocess, "Popen", FakePopen)

    from shared.job_contract import AnnotationJobRequest

    events: list[JobProgressEvent] = []
    request = AnnotationJobRequest(profile="mtb-h37rv", locus="Rv0001")
    result = executor.run_annotation_job(
        request, job_id="job-1", on_progress=events.append
    )

    assert result == result_payload
    assert [e.phase for e in events] == ["fetching", "extracting"]
    assert events[1].sections_done == 1
    assert events[1].sections_total == 2
