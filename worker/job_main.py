import argparse
import json
import os
import sys

from shared.job_contract import AnnotationJobRequest
from shared.job_progress import JobProgressEvent
from worker.executor import _run_inprocess


def _make_stderr_progress_cb(job_id: str):
    """Build a progress_cb that writes one progress NDJSON object per stderr line.

    stdout is reserved for the final result JSON only (see executor._run_subprocess),
    so all progress must travel over stderr as `{"type": "progress", ...}` lines.
    """

    def _emit(event: JobProgressEvent) -> None:
        payload = {"type": "progress", **event.model_dump(exclude_none=True)}
        payload["job_id"] = event.job_id or job_id
        try:
            sys.stderr.write(json.dumps(payload) + "\n")
            sys.stderr.flush()
        except (BrokenPipeError, OSError):
            pass

    return _emit


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run one annotation job in an isolated subprocess.")
    parser.add_argument("--request-file", required=True, help="Path to JSON AnnotationJobRequest payload.")
    args = parser.parse_args(argv)

    with open(args.request_file, encoding="utf-8") as request_file:
        request = AnnotationJobRequest(**json.load(request_file))

    job_id = os.getenv("ANNOTATION_JOB_ID")
    progress_cb = _make_stderr_progress_cb(job_id) if job_id else None

    result = _run_inprocess(request, progress_cb=progress_cb)
    json.dump(result, sys.stdout)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
