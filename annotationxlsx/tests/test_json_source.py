import json
import zipfile
from pathlib import Path

import pytest

from annotationxlsx.errors import AnnotationXlsxError
from annotationxlsx.json_source import load_annotations


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))
    return path


def test_load_single_file(tmp_path: Path):
    path = _write_json(tmp_path / 'gen_Tb927.1.100.json', {
        'gene_id': 'Tb927.1.100',
        'name': 'foo',
        'function': 'bar',
    })
    result = load_annotations(path)
    assert list(result.annotations) == ['Tb927.1.100']
    assert result.annotations['Tb927.1.100']['name'] == 'foo'
    assert result.warnings == []


def test_load_directory_recursive(tmp_path: Path):
    _write_json(tmp_path / 'nested' / 'gen_b.json', {'gene_id': 'B', 'name': 'b'})
    _write_json(tmp_path / 'gen_a.json', {'gene_id': 'A', 'name': 'a'})
    result = load_annotations(tmp_path)
    assert set(result.annotations) == {'A', 'B'}


def test_load_zip_nested(tmp_path: Path):
    zip_path = tmp_path / 'tbrucei.zip'
    with zipfile.ZipFile(zip_path, 'w') as handle:
        handle.writestr(
            'output1/annotations/tbrucei-treu927/gen_Tb927.1.100.json',
            json.dumps({'gene_id': 'Tb927.1.100', 'name': 'foo'}),
        )
        handle.writestr('output1/manifest.json', json.dumps({'run': 1}))
    result = load_annotations(zip_path)
    assert list(result.annotations) == ['Tb927.1.100']
    assert any('manifest' in warning.lower() or 'gene_id' in warning.lower() for warning in result.warnings) or result.warnings


def test_load_zip_skips_undecodable_member_with_warning(tmp_path: Path):
    zip_path = tmp_path / 'tbrucei.zip'
    with zipfile.ZipFile(zip_path, 'w') as handle:
        handle.writestr('__MACOSX/._gen_bad.json', b'\xff\xfe')
        handle.writestr('gen_good.json', json.dumps({'gene_id': 'GOOD', 'name': 'valid'}))

    result = load_annotations(zip_path)

    assert list(result.annotations) == ['GOOD']
    assert any('decode' in warning.lower() and '._gen_bad.json' in warning for warning in result.warnings)


def test_load_corrupt_zip_raises_annotation_error(tmp_path: Path):
    zip_path = tmp_path / 'corrupt.zip'
    zip_path.write_bytes(b'not a zip archive')

    with pytest.raises(AnnotationXlsxError, match='invalid zip'):
        load_annotations(zip_path)


def test_skip_invalid_and_duplicate_last_wins(tmp_path: Path, capsys):
    _write_json(tmp_path / 'bad.json', {'name': 'no id'})
    (tmp_path / 'broken.json').write_text('{not json')
    _write_json(tmp_path / 'first.json', {'gene_id': 'X', 'name': 'first'})
    _write_json(tmp_path / 'second.json', {'gene_id': 'X', 'name': 'second'})
    result = load_annotations(tmp_path)
    assert result.annotations['X']['name'] == 'second'
    assert len(result.warnings) >= 3


def test_missing_path_raises(tmp_path: Path):
    with pytest.raises(AnnotationXlsxError):
        load_annotations(tmp_path / 'missing.json')


def test_no_annotations_raises(tmp_path: Path):
    (tmp_path / 'notes.txt').write_text('hi')
    with pytest.raises(AnnotationXlsxError):
        load_annotations(tmp_path)
