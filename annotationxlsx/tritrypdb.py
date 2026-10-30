from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable

import requests

from annotationxlsx.errors import AnnotationXlsxError
from annotationxlsx.schema import empty_row, format_go_terms, format_string

BASE_URL = 'https://tritrypdb.org/tritrypdb/service'
SEARCH_PATH = (
    '/record-types/gene/searches/'
    'single_record_question_GeneRecordClasses_GeneRecordClass/reports/standard'
)
PROJECT_ID = 'TriTrypDB'
USER_AGENT = 'gene-autoannotator-annotationxlsx/1.0'
MAX_IN_FLIGHT = 4
RETRY_ATTEMPTS = 3
TIMEOUT_SECONDS = 60
RETRYABLE_STATUS = frozenset({429, 502, 503, 504})
_RETRYABLE_EXC = (
    requests.exceptions.Timeout,
    requests.exceptions.ConnectionError,
    requests.exceptions.ChunkedEncodingError,
)
Getter = Callable[..., object]


def record_to_row(gene_id: str, record: dict | None) -> dict[str, str]:
    row = empty_row(gene_id)
    if not record:
        return row
    attributes = record.get('attributes') or {}
    tables = record.get('tables') or {}
    row['name'] = format_string(attributes.get('name'))
    row['function'] = format_string(attributes.get('product'))
    row['go_terms'] = format_go_terms(tables.get('GOTerms'))
    return row


def _default_getter(url, *, params, headers, timeout):
    return requests.get(url, params=params, headers=headers, timeout=timeout)


def _extract_record(payload: object) -> dict | None:
    if not isinstance(payload, dict):
        return None
    records = payload.get('records') or []
    if not records:
        return None
    record = records[0]
    return record if isinstance(record, dict) else None


def _get_record(gene_id: str, getter: Getter, sleep) -> tuple[str, dict | None, bool]:
    url = f'{BASE_URL}{SEARCH_PATH}'
    params = {
        'primaryKeys': f'{gene_id},{PROJECT_ID}',
        'reportConfig': (
            '{"attributes":["source_id","name","product"],'
            '"tables":["GOTerms"],"attributeFormat":"text"}'
        ),
    }
    headers = {'User-Agent': USER_AGENT, 'Accept': 'application/json'}
    last_transport = False
    for attempt in range(RETRY_ATTEMPTS):
        try:
            response = getter(url, params=params, headers=headers, timeout=TIMEOUT_SECONDS)
        except _RETRYABLE_EXC:
            last_transport = True
            if sleep is not None and attempt < RETRY_ATTEMPTS - 1:
                sleep(0.5 * (attempt + 1))
            continue
        status = getattr(response, 'status_code', 200)
        if status == 404:
            return gene_id, None, False
        if status in RETRYABLE_STATUS:
            last_transport = True
            if sleep is not None and attempt < RETRY_ATTEMPTS - 1:
                sleep(0.5 * (attempt + 1))
            continue
        if 400 <= status < 500:
            return gene_id, None, False
        if status >= 500:
            return gene_id, None, True
        try:
            payload = response.json() if hasattr(response, 'json') else None
        except ValueError:
            payload = None
        return gene_id, _extract_record(payload), False
    return gene_id, None, last_transport


def fetch_rows(
    gene_ids: list[str],
    *,
    getter: Getter | None = None,
    max_workers: int = MAX_IN_FLIGHT,
    sleep=None,
) -> list[dict[str, str]]:
    getter = getter or _default_getter
    if sleep is None:
        import time
        sleep = time.sleep
    transport_failures = 0
    found: dict[str, dict | None] = {}
    workers = max(1, min(max_workers, MAX_IN_FLIGHT, len(gene_ids) or 1))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [
            pool.submit(_get_record, gene_id, getter, sleep)
            for gene_id in gene_ids
        ]
        for future in as_completed(futures):
            gene_id, record, transport = future.result()
            found[gene_id] = record
            if transport and record is None:
                transport_failures += 1
    usable = any(found.get(gene_id) is not None for gene_id in gene_ids)
    if gene_ids and not usable and transport_failures:
        raise AnnotationXlsxError('TriTrypDB request failed for every gene after retry')
    return [record_to_row(gene_id, found.get(gene_id)) for gene_id in gene_ids]
