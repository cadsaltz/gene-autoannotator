import logging
from pathlib import Path

import pytest

from experiments.paper.runners.export_review import export_run_spreadsheet


def test_export_run_spreadsheet_returns_builder_path(tmp_path):
    output = tmp_path / "team_review.xlsx"

    def builder(run_dir: Path) -> Path:
        assert run_dir == tmp_path
        output.write_text("xlsx")
        return output

    assert export_run_spreadsheet(tmp_path, builder, strict=False) == output


def test_export_run_spreadsheet_non_strict_logs_warning_and_returns_none(
    tmp_path,
    caplog,
):
    def failing_builder(_run_dir: Path) -> Path:
        raise RuntimeError("openpyxl missing")

    with caplog.at_level(logging.WARNING):
        result = export_run_spreadsheet(tmp_path, failing_builder, strict=False)

    assert result is None
    assert len(caplog.records) == 1
    assert caplog.records[0].levelno == logging.WARNING
    assert "Spreadsheet export failed" in caplog.records[0].message
    assert str(tmp_path) in caplog.records[0].message


def test_export_run_spreadsheet_strict_reraises(tmp_path):
    def failing_builder(_run_dir: Path) -> Path:
        raise RuntimeError("openpyxl missing")

    with pytest.raises(RuntimeError, match="openpyxl missing"):
        export_run_spreadsheet(tmp_path, failing_builder, strict=True)
