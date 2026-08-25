from pathlib import Path


def test_backend_is_canonical_package_with_legacy_api_shim():
    from backend.api import DEFAULT_DB_PATH, app, create_app
    from backend.job_store import JobStore
    from coordinator.api import app as legacy_app
    from coordinator.api import create_app as legacy_create_app
    from coordinator.job_store import JobStore as LegacyJobStore

    assert legacy_app is app
    assert legacy_create_app is create_app
    assert LegacyJobStore is JobStore
    assert DEFAULT_DB_PATH == Path("coordinator/jobs.sqlite3")
