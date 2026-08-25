from pathlib import Path
import subprocess
import sys


def test_backend_is_canonical_package_with_legacy_api_shim():
    from backend.api import DEFAULT_DB_PATH, app, create_app
    from coordinator.api import app as legacy_app
    from coordinator.api import create_app as legacy_create_app

    assert legacy_app is app
    assert legacy_create_app is create_app
    assert DEFAULT_DB_PATH == Path("coordinator/jobs.sqlite3")


def test_importing_coordinator_does_not_eagerly_import_backend_modules():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; import coordinator; "
                "assert not any(name == 'backend' or name.startswith('backend.') "
                "for name in sys.modules), "
                "[name for name in sys.modules "
                "if name == 'backend' or name.startswith('backend.')]"
            ),
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
