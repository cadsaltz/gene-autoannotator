import pytest
import requests

from annotationxlsx.errors import AnnotationXlsxError
from annotationxlsx.tritrypdb import BASE_URL, fetch_rows, record_to_row


class FakeResponse:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


def test_record_to_row_maps_product_name_and_go():
    record = {
        'attributes': {
            'source_id': 'Tb927.1.100',
            'name': 'foo',
            'product': 'a product',
        },
        'tables': {
            'GOTerms': [
                {'go_id': 'GO:0005739', 'go_term_name': 'mitochondrion', 'is_not': ''},
                {'go_id': 'GO:0008150', 'go_term_name': 'biological_process', 'is_not': '1'},
            ],
        },
    }
    row = record_to_row('Tb927.1.100', record)
    assert row['gene_id'] == 'Tb927.1.100'
    assert row['name'] == 'foo'
    assert row['function'] == 'a product'
    assert row['functional_category'] == ''
    assert row['drug_susc_impact'] == ''
    assert row['infection_impact'] == ''
    assert row['go_terms'] == 'GO:0005739 mitochondrion'


def test_missing_record_is_empty_row():
    row = record_to_row('Tb927.1.100', None)
    assert row['gene_id'] == 'Tb927.1.100'
    assert row['function'] == ''


def test_fetch_rows_uses_injected_getter_and_preserves_order():
    def getter(url, *, params, headers, timeout):
        assert url.startswith(BASE_URL)
        gene_id = params['primaryKeys'].split(',')[0]
        if gene_id == 'missing':
            return FakeResponse(404)
        return FakeResponse(200, {
            'records': [{
                'attributes': {'name': gene_id, 'product': f'prod-{gene_id}'},
                'tables': {'GOTerms': []},
            }],
        })

    rows = fetch_rows(['b', 'missing', 'a'], getter=getter, max_workers=1, sleep=lambda _: None)
    assert [row['gene_id'] for row in rows] == ['b', 'missing', 'a']
    assert rows[0]['function'] == 'prod-b'
    assert rows[1]['function'] == ''
    assert rows[2]['name'] == 'a'


def test_fetch_rows_hard_fails_when_all_transport_errors():
    def getter(url, *, params, headers, timeout):
        raise requests.exceptions.ConnectionError('down')

    with pytest.raises(AnnotationXlsxError):
        fetch_rows(['a', 'b'], getter=getter, max_workers=1, sleep=lambda _: None)


def test_fetch_rows_hard_fails_when_no_usable_record_and_any_transport_error():
    def getter(url, *, params, headers, timeout):
        gene_id = params['primaryKeys'].split(',')[0]
        if gene_id == 'gone':
            return FakeResponse(404)
        raise requests.exceptions.ConnectionError('down')

    with pytest.raises(AnnotationXlsxError):
        fetch_rows(['gone', 'down'], getter=getter, max_workers=1, sleep=lambda _: None)
