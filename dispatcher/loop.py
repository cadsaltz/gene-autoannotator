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


DEFAULT_MAX_JOBS_PER_WORKER = 500


@dataclass(frozen=True)
class DispatcherConfig:
    backend_url: str
    worker_api_token: str
    max_inflight: int
    max_jobs_per_worker: int
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

        raw_max_jobs_per_worker = os.getenv("DISPATCHER_MAX_JOBS_PER_WORKER", "")
        if raw_max_jobs_per_worker:
            try:
                max_jobs_per_worker = int(raw_max_jobs_per_worker)
            except ValueError as exc:
                raise RuntimeError(
                    "DISPATCHER_MAX_JOBS_PER_WORKER must be an integer"
                ) from exc
            if max_jobs_per_worker < 1:
                raise RuntimeError(
                    "DISPATCHER_MAX_JOBS_PER_WORKER must be positive"
                )
        else:
            max_jobs_per_worker = DEFAULT_MAX_JOBS_PER_WORKER

        return cls(
            backend_url=backend_url,
            worker_api_token=worker_api_token,
            max_inflight=max_inflight,
            max_jobs_per_worker=max_jobs_per_worker,
            sbatch_script=sbatch_script,
        )


def plan_launches(queued: int, inflight: int) -> int:
    """At most one HPC worker-run at a time."""
    if inflight >= 1:
        return 0
    if queued <= 0:
        return 0
    return 1


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
    to_launch = plan_launches(queued, inflight)

    script = str(Path(config.sbatch_script).expanduser())
    export = (
        f"ALL,GAA_REPO_ROOT={REPO_ROOT},"
        f"WORKER_RUN_MAX_JOBS={config.max_jobs_per_worker}"
    )
    for _ in range(to_launch):
        command_runner(
            [
                "sbatch",
                f"--export={export}",
                script,
            ],
            check=True,
        )

    return to_launch
