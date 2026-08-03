# Replace Google Sheets logging with local JSONL

**Date:** 2026-08-03  
**Status:** approved  
**Scope:** `run_pipeline.py` benchmark harness + docs/ignore + open UP-02 PR

## Problem

`run_pipeline.py` is a manual evaluation harness. After each gene annotation and `compareannotations` score, it appends a row to a hard-coded Google Spreadsheet via a service-account credential under `creds/`. That requires:

- `google-auth` / `google-api-python-client` (not pinned in `requirements.txt`, but documented in README)
- Import-time Sheets client init (script fails before any gene runs if creds are missing)
- A private spreadsheet ID and sheet name (`V2Scores`) unsuitable for upstreaming

UP-02 (PR #3 against Ethan’s repo) includes `run_pipeline.py` with this Sheets wiring. Upstream should not depend on Google Sheets or service-account secrets.

## Goals

- Remove all Google Sheets / Drive / service-account usage from `run_pipeline.py`.
- Persist the same per-gene score fields to a local JSONL file.
- Drop README guidance that installs Google client libs or mentions Sheets creds.
- Keep `creds/` gitignored; also ignore local pipeline run artifacts.
- Mirror the change onto open UP-02 so Ethan’s review never requires Sheets.

## Non-goals

- Deleting any local `creds/` files on disk.
- Changing `compareannotations` scoring logic or output.
- Migrating historical Google Sheet rows into JSONL.
- Adding a CLI/env path override for the scores file.
- Extracting a shared scores-sink module or adding a dual-write Sheets flag.

## Decisions (locked)

| Decision | Choice |
|----------|--------|
| Format | JSONL — one JSON object appended per gene |
| Default path | Repo root: `pipeline_scores.jsonl` |
| Upstream | Update fork `master` **and** force-update UP-02 branch/PR #3 |
| Gitignore | Keep `creds/`; add `pipeline_scores.jsonl`, `completed_genes.txt`, `error_log.txt` |

## Design

### `record_result`

Replace Sheets append with a local append:

```python
SCORES_LOG = "pipeline_scores.jsonl"

def record_result(gene, comparison_result, duration, num_papers_used, num_total_papers, cumulative_relevance=0.0):
    record = {
        "timestamp": datetime.now().isoformat(),
        "gene": gene,
        "comparison_result": comparison_result,
        "duration": duration,
        "num_papers_used": num_papers_used,
        "num_total_papers": num_total_papers,
        "cumulative_relevance": cumulative_relevance,
    }
    with open(SCORES_LOG, "a") as f:
        f.write(json.dumps(record) + "\n")
```

Field semantics match the former sheet columns `D:I` (`gene`, score, duration, papers used, total papers, cumulative relevance). `timestamp` is additive for local debugging and is fine to include upstream.

Call sites stay the same (success path and annotation-failure `"N/A"` path).

### Removals

Delete from `run_pipeline.py`:

- `from google.oauth2 import service_account`
- `from googleapiclient.discovery import build`
- `SERVICE_ACCOUNT_FILE`, `SCOPES`, `SPREADSHEET_URL`, `SPREADSHEET_ID`, `SHEET_NAME`
- Import-time `credentials` / `service` / `sheet` initialization

Add stdlib `json` import. Keep existing `completed_genes.txt` resume and `error_log.txt` error logging.

Module docstring / header comment should describe local JSONL logging, not Google Sheets.

### Docs

**README.md**

- Repo layout bullet: local JSONL scores, not Google Sheets logging.
- Remove the “additionally requires Google client libraries…” install block.
- Configuration / local assets: remove “`creds/` is only needed for Google Sheets”; keep a short note that `creds/` is gitignored if still listed, or drop that bullet if it becomes empty of purpose beyond ignore.

**Upstream PR queue** (`docs/superpowers/specs/2026-07-21-upstream-pr-queue-design.md`)

- UP-02 notes: no Google Sheets/creds dependency; scores go to `pipeline_scores.jsonl`.
- Global exclude already covers `.env` / credentials; no change required beyond the UP-02 note.

**WBS secrets line** mentioning “Google creds” may remain as general hygiene; clarifying it is out of scope for this change.

### `.gitignore`

Keep:

```
creds/
```

Add:

```
pipeline_scores.jsonl
completed_genes.txt
error_log.txt
```

These are local run artifacts (same class as ignored logs / generated dumps).

### UP-02 / PR #3

1. Apply the same end-state `run_pipeline.py` (and README / `.gitignore` if those paths are part of the UP-02 tree) on `upstream/UP-02-compareannotations`.
2. Push to update https://github.com/ethanbustad/gene-autoannotator/pull/3 so the reviewable tree has no Sheets client or credential path.
3. Do not reopen or rewrite UP-01 / UP-03 unless a shared README/`.gitignore` stack conflict forces a tiny follow-up; prefer only files UP-02 owns when possible.
4. Prefer amending/updating the UP-02 commit or adding a small follow-up commit on that branch — keep the PR focused on “comparison harness without Google.”

### Testing

- No live annotation run required for this change.
- Smoke-check: `record_result` appends a valid JSON line; second call appends a second line; failure `"N/A"` path still records.
- Optional: tiny unit test of a extracted pure helper is **not** required (Approach 1 — keep logic inline).

## Success criteria

- `run_pipeline.py` imports and runs without Google packages or `creds/`.
- Each scored gene appends one line to `pipeline_scores.jsonl` with the fields above.
- README no longer instructs installing Google client libs for the harness.
- `.gitignore` covers scores + existing pipeline logs; `creds/` remains ignored.
- Open UP-02 PR reflects the JSONL-backed harness.

## Out of scope follow-ups

- Optional `--scores-path` / env override.
- Importing historical sheet data.
- Broader secrets-management work from the WBS.
