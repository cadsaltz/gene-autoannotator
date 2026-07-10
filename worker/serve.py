from __future__ import annotations

import argparse
import logging
import os
import sys
from dataclasses import dataclass
from typing import Any

import ollama

from shared.job_contract import AnnotationJobRequest
from worker import capacity, executor
from worker.bootstrap import ensure_worker_env
from worker.client import CoordinatorClient
from worker.config import load_config
from worker.fleet.models import required_model_names
from worker.fleet.setup import ensure_fleet_config, refresh_fleet_footprints, reset_ollama_fleet
from worker.ollama_bootstrap import ensure_models
from worker.probe import probe_system
from worker.router import Backend, ModelRouter
from worker.router.server import start_router_server
from worker.runtime import WorkerRuntime
from worker.sources.coordinator import CoordinatorJobSource

log = logging.getLogger(__name__)


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s | %(message)s",
        stream=sys.stdout,
        force=True,
    )


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


def _should_drain(heartbeat_response: dict[str, Any], config) -> bool:
    if heartbeat_response.get("drain"):
        return True
    required_version = heartbeat_response.get("required_version")
    return required_version is not None and required_version != config.agent_version


def _execute_job(request_dict: dict[str, Any], *, job_id: str | None = None) -> dict[str, Any]:
    request = AnnotationJobRequest(**request_dict)
    return executor.run_annotation_job(request, job_id=job_id)


@dataclass
class _DrainSignal:
    draining: bool = False


class _DrainAwareCoordinatorSource(CoordinatorJobSource):
    def __init__(self, *args, drain_signal: _DrainSignal, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._drain_signal = drain_signal

    def claim_one(self):
        if self._drain_signal.draining:
            return None
        if not capacity.can_admit(_memory_available_bytes()):
            return None
        return super().claim_one()

    def is_exhausted(self) -> bool:
        return self._drain_signal.draining


def _coordinator_overrides_from_args(parsed_args: argparse.Namespace) -> dict[str, Any]:
    overrides: dict[str, Any] = {}
    if getattr(parsed_args, "coordinator_url", None):
        overrides["COORDINATOR_URL"] = parsed_args.coordinator_url
    if getattr(parsed_args, "token", None):
        overrides["WORKER_API_TOKEN"] = parsed_args.token
    if getattr(parsed_args, "memory_gb", None) is not None:
        overrides["ANNOTATION_MEMORY_BUDGET_GB"] = parsed_args.memory_gb
    return overrides


def main(args=None):
    _configure_logging()
    if args is None:
        parsed_args = argparse.Namespace()
    elif isinstance(args, argparse.Namespace):
        parsed_args = args
    elif isinstance(args, dict):
        parsed_args = argparse.Namespace(**args)
    else:
        parsed_args = argparse.Namespace()

    cli_overrides = _coordinator_overrides_from_args(parsed_args)
    bootstrap_env = bool(getattr(parsed_args, "bootstrap_env", True))
    interactive = bool(getattr(parsed_args, "interactive", sys.stdin.isatty()))
    discover_only = bool(getattr(parsed_args, "discover_only", False))
    router_host = getattr(parsed_args, "router_host", os.getenv("OLLAMA_ROUTER_HOST", "127.0.0.1"))
    router_port = int(getattr(parsed_args, "router_port", os.getenv("OLLAMA_ROUTER_PORT", "0")))

    if bootstrap_env:
        ensure_worker_env(cli_overrides=cli_overrides)

    fleet = ensure_fleet_config(interactive=interactive)
    spec = probe_system()

    if not discover_only:
        reset_ollama_fleet(fleet, spec)
        primary_host = fleet.backend_hosts()[0]
        ensure_models(client=ollama.Client(host=primary_host))
        fleet = refresh_fleet_footprints(fleet, spec, host=primary_host)

    required = set(required_model_names())
    backends = [
        Backend(host=host, models=required, parallel=fleet.parallel)
        for host in fleet.backend_hosts()
    ]
    router = ModelRouter(backends)
    router_thread = start_router_server(router, router_host, router_port, collect_metrics=False)
    os.environ["OLLAMA_ROUTER_URL"] = f"http://{router_host}:{router_thread._port}"

    config = load_config()
    client = CoordinatorClient(config)
    client.register()

    drain_signal = _DrainSignal()
    runtime_holder: dict[str, WorkerRuntime] = {}

    def free_slots() -> int:
        runtime = runtime_holder.get("runtime")
        if runtime is None:
            return config.max_slots
        return runtime.free_slots()

    source = _DrainAwareCoordinatorSource(client, free_slots_fn=free_slots, drain_signal=drain_signal)

    def heartbeat_fn(*, active_jobs: int, free_slots: int) -> None:
        if drain_signal.draining:
            state = "draining"
        else:
            state = "ready"
        response = client.heartbeat(
            active_jobs=active_jobs,
            free_slots=free_slots,
            memory_available_bytes=_memory_available_bytes(),
            cpu_percent=_cpu_percent(),
            state=state,
        )
        if not drain_signal.draining and _should_drain(response, config):
            drain_signal.draining = True
            client.heartbeat(
                active_jobs=active_jobs,
                free_slots=free_slots,
                memory_available_bytes=_memory_available_bytes(),
                cpu_percent=_cpu_percent(),
                state="draining",
            )

    runtime = WorkerRuntime(
        config=config,
        fleet_config=fleet,
        job_source=source,
        execute_fn=_execute_job,
        heartbeat_fn=heartbeat_fn,
    )
    runtime_holder["runtime"] = runtime
    runtime.run()

