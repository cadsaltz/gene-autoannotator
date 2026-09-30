"""Every env var the backend process reads must be documented in both backend env examples."""

import ast
import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = (
    REPO_ROOT / "backend.env.example",
    REPO_ROOT / "deploy" / "compose" / "backend.prod.env.example",
)
ENTRYPOINT = REPO_ROOT / "deploy" / "docker" / "backend-entrypoint.py"
APP_PACKAGES = ("backend", "shared", "autoannotation")

# Set by Dockerfile.backend for its entrypoint, never by operators.
IMAGE_INTERNAL = {"APP_DATA_DIRS", "APP_UID", "APP_GID", "APP_HOME"}
# Documented because third-party libraries the backend uses read them.
READ_BY_LIBRARIES = {"OLLAMA_HOST"}

ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]+$")
EXAMPLE_LINE = re.compile(r"^\s*#?\s*([A-Z][A-Z0-9_]+)=")
DIRECT_READERS = {"os.getenv", "getenv", "os.environ.get", "environ.get"}

LIST_MODULES = """
import json, sys
import backend.api, backend.manage
from backend.rate_limits import RATE_LIMIT_DEFAULTS
files = sorted({
    module.__file__
    for name, module in list(sys.modules.items())
    if name.split(".")[0] in %r and getattr(module, "__file__", None)
})
print(json.dumps({"files": files, "rate_limits": sorted(RATE_LIMIT_DEFAULTS)}))
""" % (APP_PACKAGES,)


def _dotted(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return f"{base}.{node.attr}" if base else None
    return None


def _first_arg(call):
    return call.args[0] if call.args else None


def _helper_functions(trees):
    """Functions that pass their first parameter to an env read, found to a fixpoint."""
    helpers = set()
    changed = True
    while changed:
        changed = False
        for tree in trees:
            for func in ast.walk(tree):
                if not isinstance(func, ast.FunctionDef) or func.name in helpers or not func.args.args:
                    continue
                param = func.args.args[0].arg
                for call in ast.walk(func):
                    if not isinstance(call, ast.Call):
                        continue
                    name = _dotted(call.func) or ""
                    arg = _first_arg(call)
                    reads = name in DIRECT_READERS or name.rsplit(".", 1)[-1] in helpers
                    if reads and isinstance(arg, ast.Name) and arg.id == param:
                        helpers.add(func.name)
                        changed = True
                        break
    return helpers


def _env_names(trees, helpers):
    names = set()
    for tree in trees:
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = _dotted(node.func) or ""
                if name in DIRECT_READERS or name.rsplit(".", 1)[-1] in helpers:
                    arg = _first_arg(node)
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        names.add(arg.value)
            elif isinstance(node, ast.Subscript) and isinstance(node.ctx, ast.Load):
                if _dotted(node.value) in {"os.environ", "environ"} and isinstance(node.slice, ast.Constant):
                    names.add(node.slice.value)
            elif isinstance(node, ast.Compare) and len(node.ops) == 1 and isinstance(node.ops[0], ast.In):
                if _dotted(node.comparators[0]) in {"os.environ", "environ"} and isinstance(node.left, ast.Constant):
                    names.add(node.left.value)
    return {name for name in names if isinstance(name, str) and ENV_NAME.match(name)}


def _backend_modules(tmp_path):
    env = {key: value for key, value in os.environ.items() if key in {"PATH", "HOME", "LANG", "SYSTEMROOT"}}
    env["PYTHONPATH"] = str(REPO_ROOT)
    # backend.api opens backend/jobs.sqlite3 relative to the cwd at import time.
    result = subprocess.run(
        [sys.executable, "-c", LIST_MODULES],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout.strip().splitlines()[-1])
    files = [Path(path) for path in data["files"]]
    return [path for path in files if REPO_ROOT in path.resolve().parents], set(data["rate_limits"])


def backend_env_names(tmp_path):
    files, rate_limit_names = _backend_modules(tmp_path)
    trees = [ast.parse(path.read_text(encoding="utf-8")) for path in [*files, ENTRYPOINT]]
    return (_env_names(trees, _helper_functions(trees)) | rate_limit_names) - IMAGE_INTERNAL


def documented_names(path):
    return {
        match.group(1)
        for line in path.read_text(encoding="utf-8").splitlines()
        if (match := EXAMPLE_LINE.match(line))
    }


def test_scanner_finds_helper_reads():
    tree = ast.parse(
        "import os\n"
        "def env_int(name, default):\n    return int(os.getenv(name) or default)\n"
        "def limit(name):\n    return env_int(name, 1)\n"
        "A = limit('SOME_LIMIT')\n"
        "B = os.environ['DIRECT_NAME']\n"
        "C = 'CHECKED' in os.environ\n"
    )
    assert _env_names([tree], _helper_functions([tree])) == {"SOME_LIMIT", "DIRECT_NAME", "CHECKED"}


def test_backend_reads_known_variables(tmp_path):
    names = backend_env_names(tmp_path)
    # Spot checks across direct reads, helpers, and the rate-limit table.
    assert {"WORKER_API_TOKEN", "SUBMISSIONS_PAUSED", "ALERT_QUEUE_DEPTH", "BACKUP_KEEP",
            "IP_SIGNUPS_PER_DAY", "MONGO_URI", "NCBI_API_KEY"} <= names


def test_every_backend_env_var_is_in_both_examples(tmp_path):
    names = backend_env_names(tmp_path)
    for example in EXAMPLES:
        missing = sorted(names - documented_names(example))
        assert not missing, f"{example.relative_to(REPO_ROOT)} does not document: {missing}"


def test_examples_only_document_variables_the_backend_reads(tmp_path):
    names = backend_env_names(tmp_path) | READ_BY_LIBRARIES
    for example in EXAMPLES:
        unknown = sorted(documented_names(example) - names)
        assert not unknown, f"{example.relative_to(REPO_ROOT)} documents unread variables: {unknown}"
