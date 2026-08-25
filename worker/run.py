from __future__ import annotations

import argparse
import json
import logging
import os
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

import ollama

from worker.bootstrap import ensure_worker_env
from worker.client import CoordinatorClient
from worker.config import load_config
from worker.fleet.models import required_model_names
from worker.fleet.setup import (
    effective_max_loaded_models,
    ensure_fleet_config,
    refresh_fleet_footprints,
    reset_ollama_fleet,
)
from worker.ollama_bootstrap import ensure_models
from worker.probe import probe_system
from worker.progress_reporter import ProgressReporter
from worker.router import Backend, ModelRouter
from worker.router.server import start_router_server, stop_router_server
from worker.runtime import JobSpec, WorkerRuntime
from worker.runtime import execute_annotation_job as _execute_job

log = logging.getLogger(__name__)


class _OneShotJobSource:
    def __init__(
        self,
        client: CoordinatorClient,
        job: JobSpec,
        reporter: ProgressReporter,
    ) -> None:
        self._client = client
        self._job = job
        self._reporter = reporter
        self.failed = False
        self._finished = False

    def claim_one(self) -> JobSpec | None:
        job, self._job = self._job, None
        return job

    def on_complete(self, job_id: str, result: Any) -> None:
        self._reporter.flush(job_id)
        self._client.complete(job_id, result)
        self._finished = True

    def on_fail(self, job_id: str, error: str, retryable: bool) -> None:
        self._reporter.flush(job_id)
        self._client.fail(job_id, error, retryable)
        self.failed = True
        self._finished = True

    def is_exhausted(self) -> bool:
        return self._finished

    def wait_or_sleep(self, timeout: float) -> None:
        time.sleep(timeout)


def _job_from_file(path: str) -> JobSpec:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return JobSpec(job_id=str(payload["job_id"]), request=dict(payload["request"]))


def _make_execute_fn(reporter: ProgressReporter):
    def execute(request_dict: dict[str, Any], *, job_id=None, on_progress=None):
        def combined_progress(event) -> None:
            reporter.report(job_id, event)
            if on_progress is not None:
                on_progress(event)

        return _execute_job(request_dict, job_id=job_id, on_progress=combined_progress)

    return execute


def _memory_available_bytes() -> int:
    try:
        import psutil

        return int(psutil.virtual_memory().available)
    except Exception:  # noqa: BLE001 - assume plenty if psutil is missing.
        return 1 << 62


def _cpu_percent() -> float:
    try:
        import psutil

        return float(psutil.cpu_percent(interval=None))
    except Exception:  # noqa: BLE001
        return 0.0


def _heartbeat_fn(client: CoordinatorClient):
    """Keep the backend's view of this allocation fresh.

    Without heartbeats the backend cannot tell a long-running Slurm job from a
    dead one: the worker looks offline while its lease is still renewed only by
    progress reports.
    """

    def heartbeat(*, active_jobs: int, free_slots: int) -> None:
        client.heartbeat(
            active_jobs=active_jobs,
            free_slots=free_slots,
            memory_available_bytes=_memory_available_bytes(),
            cpu_percent=_cpu_percent(),
            state="ready",
        )

    return heartbeat


def _deregister_quietly(client: CoordinatorClient) -> None:
    try:
        client.deregister()
    except Exception as exc:  # noqa: BLE001 - exit cleanup must never fail the run.
        log.warning("Could not deregister worker on exit: %s", exc)


def _ephemeral_worker_name(config) -> str:
    slurm_job_id = (os.getenv("SLURM_JOB_ID") or "").strip()
    if slurm_job_id:
        return f"{config.hostname}-slurm-{slurm_job_id}"
    return f"{config.hostname}-pid-{os.getpid()}"


def _bootstrap_local_fleet():
    """Provision the same supervised Ollama fleet/router used by serve and bench."""
    fleet = ensure_fleet_config(interactive=False)
    spec = probe_system()
    required = set(required_model_names())
    fleet = replace(fleet, model_count=len(required))
    max_loaded = effective_max_loaded_models(fleet)
    keep_alive = os.environ["OLLAMA_FLEET_KEEP_ALIVE"]
    os.environ["AUTOANNOTATION_OLLAMA_KEEP_ALIVE"] = keep_alive
    fleet = replace(fleet, keep_alive=keep_alive)

    supervisor = reset_ollama_fleet(fleet, spec, max_loaded=max_loaded)
    router_thread = None
    try:
        primary_host = fleet.backend_hosts()[0]
        ensure_models(client=ollama.Client(host=primary_host))
        fleet = refresh_fleet_footprints(
            fleet,
            spec,
            host=primary_host,
            measure_runtime_peak=False,
        )
        fleet = replace(
            fleet,
            max_slots=1,
            model_count=len(required),
            keep_alive=os.environ["OLLAMA_FLEET_KEEP_ALIVE"],
        )
        os.environ["AUTOANNOTATION_OLLAMA_KEEP_ALIVE"] = fleet.keep_alive

        router = ModelRouter(
            [
                Backend(host=host, models=required, parallel=fleet.parallel)
                for host in fleet.backend_hosts()
            ]
        )
        router_thread = start_router_server(
            router,
            "127.0.0.1",
            0,
            collect_metrics=False,
            fleet_supervisor=supervisor,
        )
        os.environ["OLLAMA_ROUTER_URL"] = f"http://127.0.0.1:{router_thread._port}"
        return fleet, supervisor, router_thread
    except Exception:
        if router_thread is not None:
            stop_router_server(router_thread)
        supervisor.shutdown()
        raise


def _shutdown_local_fleet(supervisor, router_thread) -> None:
    if router_thread is not None:
        stop_router_server(router_thread)
    if supervisor is not None:
        supervisor.shutdown()


def _run_job(client, config, job: JobSpec, fleet, supervisor, router_thread, *, heartbeat_fn) -> int:
    try:
        reporter = ProgressReporter(client)
        source = _OneShotJobSource(client, job, reporter)
        runtime = WorkerRuntime(
            config=replace(config, max_slots=1),
            fleet_config=fleet,
            job_source=source,
            execute_fn=_make_execute_fn(reporter),
            heartbeat_fn=heartbeat_fn,
        )
        runtime.run()
        return 1 if source.failed else 0
    finally:
        _shutdown_local_fleet(supervisor, router_thread)


def _run_claimed_job(client, config) -> int:
    claim = client.claim(1)
    if claim is None:
        return 0
    job = JobSpec(job_id=str(claim["job_id"]), request=dict(claim["request"]))
    try:
        fleet, supervisor, router_thread = _bootstrap_local_fleet()
    except Exception as exc:  # noqa: BLE001 - never strand the job we just claimed.
        client.fail(job.job_id, str(exc), retryable=True)
        return 1
    return _run_job(
        client,
        config,
        job,
        fleet,
        supervisor,
        router_thread,
        heartbeat_fn=_heartbeat_fn(client),
    )


def main(args: argparse.Namespace) -> int:
    ensure_worker_env(interactive=False, skip_fleet_config=True)
    config = load_config()

    if bool(getattr(args, "claim_one", False)):
        config = replace(
            config,
            worker_name=_ephemeral_worker_name(config),
            max_slots=1,
        )
        client = CoordinatorClient(config)
        client.register()
        try:
            return _run_claimed_job(client, config)
        finally:
            # The allocation is ending, so drop the registration instead of
            # leaving a phantom worker until the offline window elapses.
            _deregister_quietly(client)

    client = CoordinatorClient(config)
    job = _job_from_file(args.job_file)
    fleet, supervisor, router_thread = _bootstrap_local_fleet()
    return _run_job(
        client,
        config,
        job,
        fleet,
        supervisor,
        router_thread,
        heartbeat_fn=None,
    )
