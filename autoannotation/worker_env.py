"""Load worker.env into the current process environment."""

from __future__ import annotations

import os
from pathlib import Path


def load_worker_env_into_process(*, env_path: Path | None = None) -> Path:
    """Load worker.env into os.environ via setdefault. Returns path used."""
    from shared.env_persist import load_env_file
    from worker.bootstrap import default_env_path

    path = env_path or default_env_path()
    for key, value in load_env_file(path).items():
        os.environ.setdefault(key, value)
    return path
