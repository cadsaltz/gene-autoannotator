import argparse
from pathlib import Path

from worker.bench import DEFAULT_LOG_FILENAME, _resolve_log_file


def test_resolve_log_file_prefers_output_dir(tmp_path: Path):
    args = argparse.Namespace(
        log_file=None,
        output_dir=str(tmp_path / "annotations"),
    )
    report = tmp_path / "reports" / "bench.json"
    path = _resolve_log_file(args=args, dashboard=True, report_path=report)
    assert path == (tmp_path / "annotations").resolve() / DEFAULT_LOG_FILENAME
