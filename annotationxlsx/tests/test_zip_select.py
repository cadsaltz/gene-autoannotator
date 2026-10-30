from pathlib import Path

import pytest

from annotationxlsx.errors import AnnotationXlsxError
from annotationxlsx.zip_select import select_tbrucei_zip


def test_dated_filename_wins_over_newer_mtime(tmp_path: Path):
    older_dated = tmp_path / 'tbrucei-treu927-ge10-results_20261022.zip'
    newer_undated = tmp_path / 'tbrucei-treu927-ge10-results.zip'
    older_dated.write_bytes(b'a')
    newer_undated.write_bytes(b'b')
    Path(newer_undated).touch()
    assert select_tbrucei_zip(tmp_path) == older_dated


def test_later_date_wins(tmp_path: Path):
    first = tmp_path / 'tbrucei_20260101.zip'
    second = tmp_path / 'tbrucei_20261022.zip'
    first.write_bytes(b'a')
    second.write_bytes(b'b')
    assert select_tbrucei_zip(tmp_path) == second


def test_mtime_when_no_dates(tmp_path: Path):
    first = tmp_path / 'tbrucei-a.zip'
    second = tmp_path / 'tbrucei-b.zip'
    first.write_bytes(b'a')
    second.write_bytes(b'b')
    import os
    os.utime(first, (1, 1))
    os.utime(second, (2, 2))
    assert select_tbrucei_zip(tmp_path) == second


def test_missing_raises(tmp_path: Path):
    with pytest.raises(AnnotationXlsxError):
        select_tbrucei_zip(tmp_path)
