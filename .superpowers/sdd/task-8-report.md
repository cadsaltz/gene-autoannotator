# Task 8 Report: Package rename coordinator to backend

**Status:** Complete

## Implementation

- Moved the canonical FastAPI package from `coordinator/` to `backend/`.
- Updated Python imports, tests, uvicorn targets, Compose service wiring,
  Docker image contents, and user/deployment documentation.
- Added a one-release `coordinator` compatibility package that aliases backend
  submodules, including `coordinator.api`.
- Preserved `DEFAULT_DB_PATH = coordinator/jobs.sqlite3` and the
  `/state/coordinator` Compose volume path so existing SQLite state remains
  available.

## Verification

- Focused backend and compatibility suite: 146 passed.
- Python package compilation and PyYAML Compose/import checks passed.
- CI-equivalent suite: 743 passed, 10 skipped, 13 unrelated pre-existing
  failures in fleet sizing, gene-name fixtures, GO configuration, Ollama
  version expectations, and worker bench/serve mocks.
- Docker Compose CLI validation was unavailable because Docker is not installed.

## Commit

- `refactor: rename coordinator package to backend`

## Concerns

- The repository already tracks `backend/jobs.sqlite3`; this task leaves that
  historical database file unchanged and adds backend SQLite patterns to
  `.gitignore` for future generated files.

## Important Finding Follow-up

- Migrated all remaining test imports to `backend.*`, except the intentional
  `coordinator.api` compatibility assertions in `test_backend_package.py`.
- Reduced `coordinator/__init__.py` to a package marker so importing
  `coordinator` no longer eagerly imports backend modules; `coordinator/api.py`
  remains the thin legacy API shim.
- Added a subprocess regression test proving the package import is lazy.
- Focused backend and migrated-test suite: 87 passed.
- Python compilation check for `backend` and `coordinator`: passed.
