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
