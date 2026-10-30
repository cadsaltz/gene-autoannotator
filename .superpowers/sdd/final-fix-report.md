# annotationxlsx Important Findings Fix Report

## Scope

- Surface missing TriTrypDB records and partial transport failures as CLI warnings.
- Keep JSON CLI output sorted by `gene_id`.
- Skip undecodable JSON inputs with warnings and convert corrupt zip errors to `AnnotationXlsxError`.
- Filter GO terms only for known true `is_not` values.

## TDD evidence

Command:

```text
/home/caden-saltzberg/projects/sch/gene-autoannotator/.venv/bin/python -m pytest annotationxlsx/tests/test_tritrypdb.py annotationxlsx/tests/test_json_source.py annotationxlsx/tests/test_cli.py -q
```

Initial output before production changes:

```text
6 failed, 28 passed in 0.80s
```

Output after production changes:

```text
34 passed in 0.58s
```

## Full verification

Command:

```text
/home/caden-saltzberg/projects/sch/gene-autoannotator/.venv/bin/python -m pytest annotationxlsx/tests -v
```

Output:

```text
collected 52 items
============================== 52 passed in 0.71s ==============================
```

Command:

```text
git diff --check
```

Output: no errors.
