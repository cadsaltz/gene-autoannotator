import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
HEAVY_MODULES = ("torch", "transformers", "sentence_transformers", "spacy")

BLOCKER = f"""
import sys

BLOCKED = {HEAVY_MODULES!r}


class _Blocker:
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in BLOCKED:
            raise ImportError(f"slim backend image must not import {{name}}")
        return None


sys.meta_path.insert(0, _Blocker())
"""


def _run_blocked(tmp_path, code):
    site_dir = tmp_path / "site"
    site_dir.mkdir()
    (site_dir / "sitecustomize.py").write_text(BLOCKER, encoding="utf-8")
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    env = {
        key: value
        for key, value in os.environ.items()
        if key in {"PATH", "HOME", "LANG", "LC_ALL", "SYSTEMROOT"}
    }
    env["PYTHONPATH"] = os.pathsep.join([str(site_dir), str(REPO_ROOT)])
    # backend.api opens backend/jobs.sqlite3 relative to the cwd at import time.
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=work_dir,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_blocker_rejects_heavy_imports(tmp_path):
    result = _run_blocked(tmp_path, "import torch")
    assert result.returncode != 0
    assert "slim backend image must not import torch" in result.stderr


def test_backend_api_imports_without_heavy_ml_packages(tmp_path):
    result = _run_blocked(tmp_path, "import backend.api, backend.manage")
    assert result.returncode == 0, result.stderr


def test_backend_requirements_exclude_heavy_packages():
    lines = (REPO_ROOT / "requirements-backend.txt").read_text(encoding="utf-8").splitlines()
    names = {
        re.split(r"[<>=\[;\s]", line.strip(), maxsplit=1)[0].lower().replace("_", "-")
        for line in lines
        if line.strip() and not line.strip().startswith("#")
    }
    heavy = {"torch", "transformers", "sentence-transformers", "spacy", "triton"}
    assert not names & heavy
    assert not any(name.startswith(("nvidia-", "cuda-")) for name in names)
    assert {"fastapi", "uvicorn", "pymongo", "pydantic"} <= names
