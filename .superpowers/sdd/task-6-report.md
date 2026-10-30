# Task 6 Report: TriTrypDB client (mocked HTTP)

## Status

DONE

## Commit

`b8bd74c` feat: fetch TriTrypDB gene product, name, and GO terms

Not pushed. Hooks were not skipped. Pre-existing dirty `.superpowers/sdd/progress.md`, `task-2-report.md`, and `task-3-report.md` were left unstaged. This report is uncommitted.

## What you implemented

`annotationxlsx.tritrypdb` fetches one TriTrypDB gene record per id and maps it onto an annotation row. Tests inject `getter`. Nothing in the tests calls the network.

Constants (verbatim):

- `BASE_URL = "https://tritrypdb.org/tritrypdb/service"`
- `SEARCH_PATH = "/record-types/gene/searches/single_record_question_GeneRecordClasses_GeneRecordClass/reports/standard"`
- `PROJECT_ID = "TriTrypDB"`
- `USER_AGENT = "gene-autoannotator-annotationxlsx/1.0"`
- `MAX_IN_FLIGHT = 4`
- `RETRY_ATTEMPTS = 3`
- `RETRYABLE_STATUS = frozenset({429, 502, 503, 504})`
- `TIMEOUT_SECONDS = 60`

`record_to_row(gene_id, record)` starts from `empty_row`. `attributes.name` → `name`, `attributes.product` → `function` via `format_string`. `tables.GOTerms` → `go_terms` via `format_go_terms` (so `is_not` terms are dropped). `functional_category`, `drug_susc_impact`, and `infection_impact` stay empty. `record is None` (or otherwise falsey) returns the empty row with `gene_id` set.

`fetch_rows(gene_ids, *, getter=None, max_workers=4, sleep=None)`:

- Default getter is `requests.get`. Default sleep is `time.sleep`.
- Query is `primaryKeys={gene_id},TriTrypDB` plus the standard report config for `source_id`, `name`, `product`, and `GOTerms`.
- Unwraps `{"records": [record]}`. Empty `records`, a non-dict body, or HTTP 404 is a missing gene (empty row, not a transport failure).
- Timeout, connection error, chunked-encoding error, and statuses in `RETRYABLE_STATUS` retry up to `RETRY_ATTEMPTS`, with backoff `0.5 * (attempt + 1)` when sleep is set and attempts remain.
- Other statuses `>= 400` follow the same retry-and-count-as-transport path from the brief snippet.
- At most `max_workers` (capped by `MAX_IN_FLIGHT` default and by the id count) requests in flight. Output order matches input `gene_ids`.
- Raises `AnnotationXlsxError` (`TriTrypDB request failed for every gene after retry`) only when the id list is non-empty, no gene produced a usable record, and at least one transport/HTTP failure remained after retry.

No `autoannotation` import.

## Files

- `annotationxlsx/tritrypdb.py` (new)
- `annotationxlsx/tests/test_tritrypdb.py` (new)

## TDD RED

Tests were written first. `annotationxlsx/tritrypdb.py` did not exist.

Command:

```
cd /home/caden-saltzberg/projects/sch/gene-autoannotator/.worktrees/annotation-xlsx && /home/caden-saltzberg/projects/sch/gene-autoannotator/.venv/bin/python -m pytest annotationxlsx/tests/test_tritrypdb.py -v
```

Exit code 2.

```
============================= test session starts ==============================
platform linux -- Python 3.12.3, pytest-9.0.3, pluggy-1.6.0 -- /home/caden-saltzberg/projects/sch/gene-autoannotator/.venv/bin/python
cachedir: .pytest_cache
rootdir: /home/caden-saltzberg/projects/sch/gene-autoannotator/.worktrees/annotation-xlsx
plugins: anyio-4.13.0
collecting ... collected 0 items / 1 error

==================================== ERRORS ====================================
___________ ERROR collecting annotationxlsx/tests/test_tritrypdb.py ____________
ImportError while importing test module '/home/caden-saltzberg/projects/sch/gene-autoannotator/.worktrees/annotation-xlsx/annotationxlsx/tests/test_tritrypdb.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
/usr/lib/python3.12/importlib/__init__.py:90: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
annotationxlsx/tests/test_tritrypdb.py:5: in <module>
    from annotationxlsx.tritrypdb import BASE_URL, fetch_rows, record_to_row
E   ModuleNotFoundError: No module named 'annotationxlsx.tritrypdb'
=========================== short test summary info ============================
ERROR annotationxlsx/tests/test_tritrypdb.py
!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
=============================== 1 error in 0.51s ===============================
```

Failure reason matches the brief: `ModuleNotFoundError: No module named 'annotationxlsx.tritrypdb'`.

## TDD GREEN

Command after adding `annotationxlsx/tritrypdb.py` (exit code 0):

```
cd /home/caden-saltzberg/projects/sch/gene-autoannotator/.worktrees/annotation-xlsx && /home/caden-saltzberg/projects/sch/gene-autoannotator/.venv/bin/python -m pytest annotationxlsx/tests/test_tritrypdb.py annotationxlsx/tests/test_schema.py -v
```

```
============================= test session starts ==============================
platform linux -- Python 3.12.3, pytest-9.0.3, pluggy-1.6.0 -- /home/caden-saltzberg/projects/sch/gene-autoannotator/.venv/bin/python
cachedir: .pytest_cache
rootdir: /home/caden-saltzberg/projects/sch/gene-autoannotator/.worktrees/annotation-xlsx
plugins: anyio-4.13.0
collecting ... collected 12 items

annotationxlsx/tests/test_tritrypdb.py::test_record_to_row_maps_product_name_and_go PASSED [  8%]
annotationxlsx/tests/test_tritrypdb.py::test_missing_record_is_empty_row PASSED [ 16%]
annotationxlsx/tests/test_tritrypdb.py::test_fetch_rows_uses_injected_getter_and_preserves_order PASSED [ 25%]
annotationxlsx/tests/test_tritrypdb.py::test_fetch_rows_hard_fails_when_all_transport_errors PASSED [ 33%]
annotationxlsx/tests/test_tritrypdb.py::test_fetch_rows_hard_fails_when_no_usable_record_and_any_transport_error PASSED [ 41%]
annotationxlsx/tests/test_schema.py::test_columns_order PASSED           [ 50%]
annotationxlsx/tests/test_schema.py::test_null_and_missing_become_empty PASSED [ 58%]
annotationxlsx/tests/test_schema.py::test_string_list_joins_with_semicolon_space PASSED [ 66%]
annotationxlsx/tests/test_schema.py::test_go_terms_sorted_unique_skip_not PASSED [ 75%]
annotationxlsx/tests/test_schema.py::test_annotation_to_row_reads_biology_fields_only PASSED [ 83%]
annotationxlsx/tests/test_schema.py::test_empty_row_has_only_gene_id PASSED [ 91%]
annotationxlsx/tests/test_schema.py::test_truncate_cell_notes_overflow PASSED [100%]

============================== 12 passed in 0.14s ==============================
```

## Concerns

- The design’s missing-gene path is a soft warning plus an empty row. This client returns the empty row and does not warn. A later CLI task can emit the warning.
- Statuses `>= 400` other than 404 are retried and counted as transport failures, matching the brief snippet. The design text lists only timeout, connection error, 429, 502, 503, and 504. A 400 or 500 therefore looks like a missing gene when any other gene succeeded, and can hard-fail the batch when nothing succeeded.
- Retry counts, backoff, empty `records`, and retryable HTTP statuses are implemented and not covered by the brief’s tests. Tests inject `getter` and do not call TriTrypDB.

## Important review findings fix

Status: DONE

Changes:

- Capped the executor at `min(max_workers, MAX_IN_FLIGHT, len(gene_ids) or 1)`, with a minimum of one worker.
- Treated JSON decode errors, non-dict bodies, and empty records as missing genes.
- Limited retries to timeout/connection/chunked errors and HTTP 429/502/503/504. Other 4xx responses are missing genes; other 5xx responses are one-attempt transport failures.
- Added focused tests for all three findings.

TDD RED command:

```
/home/caden-saltzberg/projects/sch/gene-autoannotator/.venv/bin/python -m pytest annotationxlsx/tests/test_tritrypdb.py -v
```

Result: exit 1; 12 collected, 4 failed and 8 passed. The failures showed 8 workers instead of 4, an escaping JSON decode exception, HTTP 400 raising after retries instead of returning a missing gene, and HTTP 500 making 3 attempts instead of 1.

Covering verification command:

```
/home/caden-saltzberg/projects/sch/gene-autoannotator/.venv/bin/python -m pytest annotationxlsx/tests/test_tritrypdb.py annotationxlsx/tests/test_schema.py -v
```

Result: exit 0; `19 passed in 0.14s`.

IDE lint result: no linter errors in `annotationxlsx/tritrypdb.py` or `annotationxlsx/tests/test_tritrypdb.py`.
