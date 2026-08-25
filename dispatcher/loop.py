from __future__ import annotations

import getpass
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import httpx

SLURM_JOB_NAME = "gene-autoannotator-run"
REPO_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class DispatcherConfig:
    backend_url: str
    worker_api_token: str
    max_inflight: int
    sbatch_script: str

    @classmethod
    def from_env(cls) -> "DispatcherConfig":
        backend_url = (
            os.getenv("BACKEND_URL") or os.getenv("COORDINATOR_URL") or ""
        ).rstrip("/")
        if not backend_url:
            raise RuntimeError(
                "BACKEND_URL (or legacy COORDINATOR_URL) is required"
            )

        worker_api_token = os.getenv("WORKER_API_TOKEN", "")
        if not worker_api_token:
            raise RuntimeError("WORKER_API_TOKEN is required")

        raw_max_inflight = os.getenv("DISPATCHER_MAX_INFLIGHT", "")
        if not raw_max_inflight:
            raise RuntimeError("DISPATCHER_MAX_INFLIGHT is required")
        try:
            max_inflight = int(raw_max_inflight)
        except ValueError as exc:
            raise RuntimeError("DISPATCHER_MAX_INFLIGHT must be an integer") from exc
        if max_inflight < 0:
            raise RuntimeError("DISPATCHER_MAX_INFLIGHT must be non-negative")

        sbatch_script = os.getenv("DISPATCHER_SBATCH_SCRIPT", "")
        if not sbatch_script:
            raise RuntimeError("DISPATCHER_SBATCH_SCRIPT is required")

        return cls(
            backend_url=backend_url,
            worker_api_token=worker_api_token,
            max_inflight=max_inflight,
            sbatch_script=sbatch_script,
        )


def plan_launches(queued: int, inflight: int, max_inflight: int) -> int:
    """Return the number of workers that fit both queue depth and Slurm capacity."""
    return max(0, min(queued, max_inflight - inflight))


def _peek_queued(
    config: DispatcherConfig,
    http_get: Callable[..., Any],
) -> int:
    backend_url = config.backend_url.rstrip("/")
    response = http_get(
        f"{backend_url}/jobs/queue-summary",
        headers={"Authorization": f"Bearer {config.worker_api_token}"},
        timeout=30.0,
    )
    response.raise_for_status()
    queued = response.json()["queued"]
    if not isinstance(queued, int) or isinstance(queued, bool) or queued < 0:
        raise RuntimeError("queue-summary returned an invalid queued count")
    return queued


def _count_inflight(
    command_runner: Callable[..., Any],
    user: str,
) -> int:
    result = command_runner(
        [
            "squeue",
            "--noheader",
            "--user",
            user,
            "--name",
            SLURM_JOB_NAME,
            "--format=%i",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return sum(1 for line in result.stdout.splitlines() if line.strip())


def dispatch_once(
    config: DispatcherConfig | None = None,
    *,
    http_get: Callable[..., Any] | None = None,
    command_runner: Callable[..., Any] | None = None,
    user: str | None = None,
) -> int:
    """Peek queue depth and submit one claim-on-start worker per available slot."""
    config = config or DispatcherConfig.from_env()
    http_get = http_get or httpx.get
    command_runner = command_runner or subprocess.run
    user = user or os.getenv("USER") or getpass.getuser()

    queued = _peek_queued(config, http_get)
    inflight = _count_inflight(command_runner, user)
    to_launch = plan_launches(queued, inflight, config.max_inflight)

    script = str(Path(config.sbatch_script).expanduser())
    for _ in range(to_launch):
        command_runner(
            [
                "sbatch",
                f"--export=ALL,GAA_REPO_ROOT={REPO_ROOT}",
                script,
            ],
            check=True,
        )

    return to_launch
