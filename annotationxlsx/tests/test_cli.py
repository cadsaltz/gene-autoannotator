import json
import zipfile
from pathlib import Path

from openpyxl import load_workbook

from annotationxlsx.__main__ import main
from annotationxlsx.schema import COLUMNS


def _ann(gene_id: str, **fields) -> dict:
    payload = {
        'gene_id': gene_id,
        'name': fields.get('name', gene_id),
        'function': fields.get('function'),
        'functional_category': fields.get('functional_category'),
        'drug_susc_impact': fields.get('drug_susc_impact'),
        'infection_impact': fields.get('infection_impact'),
        'go_terms': fields.get('go_terms'),
    }
    return payload


def test_json_file_directory_and_zip(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    one = tmp_path / 'one.json'
    one.write_text(json.dumps(_ann('Tb927.2.200', name='b', function='fb')))
    nested = tmp_path / 'dir' / 'nested'
    nested.mkdir(parents=True)
    (nested / 'a.json').write_text(json.dumps(_ann(
        'Tb927.1.100',
        name='a',
        function='fa',
        functional_category=['cat1', 'cat2'],
        go_terms=[{'id': 'GO:0005739', 'name': 'mitochondrion'}],
    )))
    zip_path = tmp_path / 'in.zip'
    with zipfile.ZipFile(zip_path, 'w') as handle:
        handle.writestr('output1/gen_c.json', json.dumps(_ann('Tb927.3.300', name='c')))

    workbook = tmp_path / 'cmp.xlsx'
    assert main(['json', '--input', str(one), '--workbook', str(workbook)]) == 0
    ws = load_workbook(workbook)['generated']
    assert [cell.value for cell in ws[1]] == list(COLUMNS)
    assert ws['A2'].value == 'Tb927.2.200'

    assert main(['json', '--input', str(tmp_path / 'dir'), '--workbook', str(workbook)]) == 0
    ws = load_workbook(workbook)['generated']
    assert ws['A2'].value == 'Tb927.1.100'
    assert ws['D2'].value == 'cat1; cat2'
    assert ws['G2'].value == 'GO:0005739 mitochondrion'

    assert main(['json', '--input', str(zip_path), '--workbook', str(workbook)]) == 0
    ws = load_workbook(workbook)['generated']
    assert ws['A2'].value == 'Tb927.3.300'


def test_json_rejects_xls(tmp_path: Path):
    src = tmp_path / 'a.json'
    src.write_text(json.dumps(_ann('Tb927.1.100')))
    assert main(['json', '--input', str(src), '--workbook', str(tmp_path / 'out.xls')]) == 1


def test_json_missing_input_is_hard_fail(tmp_path: Path):
    assert main(['json', '--input', str(tmp_path / 'missing.json'), '--workbook', str(tmp_path / 'out.xlsx')]) == 1
