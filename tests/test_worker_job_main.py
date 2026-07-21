"""Regression tests for worker subprocess stdout contract."""

import io
import json
import sys
from contextlib import redirect_stdout

import pytest

from shared.job_contract import AnnotationJobRequest
from worker import executor, job_main


def _minimal_annotation_result(*, locus="Rv0001"):
    return {
        "gene_distillation": json.dumps({"gene_id": locus, "name": "test-gene"}),
        "gene_annotation": {
            "gene_id": locus,
            "name": "test-gene",
            "annotation_metadata": {"profile_id": "mtb-h37rv"},
        },
        "pmc_ids": ["PMC123"],
        "used_ids": ["PMC123"],
        "cumulative_relevance": 1.0,
        "selection_mode": "relevance_budget",
    }


def test_job_main_stdout_is_valid_json(monkeypatch, tmp_path):
    """Worker bench parses subprocess stdout as JSON; CLI prints must not leak."""
    request_path = tmp_path / "request.json"
    request = AnnotationJobRequest(
        profile="mtb-h37rv",
        locus="Rv0001",
        allow_online_name_lookup=False,
    )
    request_path.write_text(request.model_dump_json(), encoding="utf-8")

    monkeypatch.setenv("ANNOTATION_JOB_ID", "bench-001")
    monkeypatch.setenv("WORKER_OUTPUT_DIR", str(tmp_path / "out"))
    # Patch the CLI binding used by the in-process executor, not only the
    # defining module (from-import keeps a local reference).
    monkeypatch.setattr(
        "autoannotation.__main__.get_gene_annotation",
        lambda **_kwargs: _minimal_annotation_result(),
    )

    buffer = io.StringIO()
    with redirect_stdout(buffer):
        job_main.main(["--request-file", str(request_path)])

    stdout = buffer.getvalue()
    assert stdout.startswith("{"), f"stdout must be JSON only, got: {stdout[:120]!r}"
    payload = json.loads(stdout)
    assert payload["annotation"]["gene_id"] == "Rv0001"
    assert (tmp_path / "out" / "gen_Rv0001.json").is_file()


def test_annotation_main_prints_cli_output_without_job_id(capsys, monkeypatch):
    monkeypatch.delenv("ANNOTATION_JOB_ID", raising=False)
    monkeypatch.setattr(
        "autoannotation.__main__.get_gene_annotation",
        lambda **_kwargs: _minimal_annotation_result(locus="Rv2612c"),
    )

    from autoannotation.__main__ import main

    main(profile="mtb-h37rv", locus="Rv2612c", no_online_name_lookup=True)

    captured = capsys.readouterr()
    assert "Rv2612c" in captured.out
    assert "Number of papers used" in captured.out


def test_subprocess_executor_rejects_polluted_stdout(monkeypatch):
    """Documents the failure mode seen in bench: non-JSON prefix on stdout."""
    monkeypatch.setenv("WORKER_JOB_EXECUTION", "subprocess")

    polluted_stdout = (
        "Rv2612c\n"
        '{"gene_id": "Rv2612c"}\n'
        'Number of papers used: 3\n'
        '{"annotation": {"gene_id": "Rv2612c"}, "output_path": "gen_json/gen_Rv2612c.json"}\n'
    )

    class FakePopen:
        def __init__(self):
            self.stdout = io.StringIO(polluted_stdout)
            self.stderr = io.StringIO("")
            self.returncode = None

        def wait(self, timeout=None):
            self.returncode = 0
            return self.returncode

    monkeypatch.setattr(executor.subprocess, "Popen", lambda *a, **k: FakePopen())

    request = AnnotationJobRequest(profile="mtb-h37rv", locus="Rv2612c")
    with pytest.raises(RuntimeError, match="stdout is not valid JSON"):
        executor.run_annotation_job(request, job_id="bench-002")


def test_subprocess_executor_accepts_clean_stdout(monkeypatch):
    monkeypatch.setenv("WORKER_JOB_EXECUTION", "subprocess")

    clean_stdout = json.dumps(
        {"annotation": {"gene_id": "Rv2612c"}, "output_path": "gen_json/gen_Rv2612c.json"}
    )

    class FakePopen:
        def __init__(self):
            self.stdout = io.StringIO(clean_stdout)
            self.stderr = io.StringIO("")
            self.returncode = None

        def wait(self, timeout=None):
            self.returncode = 0
            return self.returncode

    monkeypatch.setattr(executor.subprocess, "Popen", lambda *a, **k: FakePopen())

    request = AnnotationJobRequest(profile="mtb-h37rv", locus="Rv2612c")
    result = executor.run_annotation_job(request, job_id="bench-002")
    assert result["annotation"]["gene_id"] == "Rv2612c"
