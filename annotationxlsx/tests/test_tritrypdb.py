import pytest
import requests

from annotationxlsx.errors import AnnotationXlsxError
from annotationxlsx.tritrypdb import BASE_URL, MAX_IN_FLIGHT, fetch_rows, record_to_row


class FakeResponse:
    def __init__(self, status_code, payload=None, json_error=None):
        self.status_code = status_code
        self._payload = payload
        self._json_error = json_error

    def json(self):
        if self._json_error is not None:
            raise self._json_error
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


def test_fetch_rows_caps_requested_workers(monkeypatch):
    observed = {}

    class ImmediateFuture:
        def __init__(self, result):
            self._result = result

        def result(self):
            return self._result

    class CapturingExecutor:
        def __init__(self, *, max_workers):
            observed['max_workers'] = max_workers

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def submit(self, function, *args):
            return ImmediateFuture(function(*args))

    monkeypatch.setattr('annotationxlsx.tritrypdb.ThreadPoolExecutor', CapturingExecutor)
    monkeypatch.setattr('annotationxlsx.tritrypdb.as_completed', lambda futures: futures)

    rows = fetch_rows(
        [f'gene-{index}' for index in range(8)],
        getter=lambda *args, **kwargs: FakeResponse(404),
        max_workers=20,
        sleep=lambda _: None,
    )

    assert observed['max_workers'] == MAX_IN_FLIGHT
    assert len(rows) == 8


@pytest.mark.parametrize(
    'response',
    [
        FakeResponse(200, json_error=ValueError('invalid JSON')),
        FakeResponse(200, payload=[]),
        FakeResponse(200, payload={'records': []}),
    ],
)
def test_fetch_rows_treats_invalid_or_empty_body_as_missing(response):
    rows = fetch_rows(
        ['missing'],
        getter=lambda *args, **kwargs: response,
        max_workers=1,
        sleep=lambda _: None,
    )

    assert rows == [record_to_row('missing', None)]


@pytest.mark.parametrize('status_code', [400, 404])
def test_fetch_rows_treats_nonretryable_4xx_as_missing_without_retry(status_code):
    attempts = 0

    def getter(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        return FakeResponse(status_code)

    rows = fetch_rows(['missing'], getter=getter, max_workers=1, sleep=lambda _: None)

    assert attempts == 1
    assert rows == [record_to_row('missing', None)]


def test_fetch_rows_treats_nonretryable_5xx_as_transport_failure_without_retry():
    attempts = 0

    def getter(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        return FakeResponse(500)

    with pytest.raises(AnnotationXlsxError):
        fetch_rows(['failed'], getter=getter, max_workers=1, sleep=lambda _: None)

    assert attempts == 1
