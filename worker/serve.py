from __future__ import annotations

import argparse
import logging
import os
import sys
import threading
from dataclasses import replace
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import ollama

from shared.job_contract import AnnotationJobRequest
from shared.job_progress import JobProgressEvent
from worker import capacity, executor
from worker.bench import configure_bench_logging
from worker.bench_dashboard import BenchDashboard
from worker.bootstrap import ensure_worker_env
from worker.client import CoordinatorClient
from worker.config import load_config
from worker.fleet import models as fleet_models
from worker.fleet import sizing
from worker.fleet.models import required_model_names
from worker.fleet.setup import ensure_fleet_config, refresh_fleet_footprints, reset_ollama_fleet
from worker.fleet.supervisor import FleetSupervisor
from worker.ollama_bootstrap import ensure_models
from worker.ollama_keep_alive import resolve_job_keep_alive
from worker.probe import probe_system
from worker.progress_reporter import ProgressReporter
from worker.router import Backend, ModelRouter
from worker.router.ollama_ps import residency_snapshot_from_ps
from worker.router.residency import pack_factor_from_env, select_residency_mode
from worker.router.server import start_router_server
from worker.runtime import WorkerRuntime
from worker.sources.coordinator import CoordinatorJobSource
from worker.bench import _build_model_memory_cache

DEFAULT_LOG_FILENAME = "worker-serve.log"

log = logging.getLogger(__name__)


def _configure_logging(*, log_file: Path | None = None, dashboard: bool = False) -> None:
    configure_bench_logging(log_file=log_file, dashboard=dashboard)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def _dashboard_enabled(args: argparse.Namespace) -> bool:
    no_dashboard = bool(getattr(args, "no_dashboard", False))
    env_flag = os.getenv("WORKER_SERVE_DASHBOARD", "1")
    return sys.stdout.isatty() and not no_dashboard and env_flag != "0"


def _resolve_log_file(*, args: argparse.Namespace, dashboard: bool) -> Path | None:
    explicit = getattr(args, "log_file", None) or os.getenv("WORKER_LOG_FILE")
    if explicit:
        return Path(explicit)
    if not dashboard:
        return None
    output_dir = os.getenv("WORKER_OUTPUT_DIR")
    if output_dir:
        return Path(output_dir).expanduser().resolve() / DEFAULT_LOG_FILENAME
    return Path.cwd() / DEFAULT_LOG_FILENAME


def _run_with_dashboard(
    runtime: WorkerRuntime,
    *,
    dashboard: bool,
    meta: dict[str, Any],
    meta_provider: Any | None = None,
) -> None:
    if not dashboard:
        runtime.run()
        return

    # Blank line between setup logs and the live dashboard panel.
    print(flush=True)
    stop_event = threading.Event()
    dashboard_thread = threading.Thread(
        target=BenchDashboard().run_live,
        args=(runtime, stop_event),
        kwargs={"meta": meta, "meta_provider": meta_provider},
        name="worker-serve-dashboard",
        daemon=True,
    )
    dashboard_thread.start()
    try:
        runtime.run()
    finally:
        stop_event.set()
        dashboard_thread.join(timeout=5)


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


def _execute_job(
    request_dict: dict[str, Any],
    *,
    job_id: str | None = None,
    on_progress=None,
) -> dict[str, Any]:
    request = AnnotationJobRequest(**request_dict)
    return executor.run_annotation_job(request, job_id=job_id, on_progress=on_progress)


def _make_execute_fn(reporter: ProgressReporter):
    """Wrap `_execute_job` so every progress event is both reported to the
    coordinator (debounced) and forwarded to the runtime's own on_progress
    hook (used for in-memory job snapshots), regardless of which caller
    passes `on_progress` down through `WorkerRuntime`.
    """

    def execute(request_dict: dict[str, Any], *, job_id=None, on_progress=None) -> dict[str, Any]:
        def combined_progress(event: JobProgressEvent) -> None:
            reporter.report(job_id, event)
            if on_progress is not None:
                on_progress(event)

        return _execute_job(request_dict, job_id=job_id, on_progress=combined_progress)

    return execute


@dataclass
class _DrainSignal:
    draining: bool = False


class _DrainAwareCoordinatorSource(CoordinatorJobSource):
    def __init__(
        self,
        *args,
        drain_signal: _DrainSignal,
        reporter: ProgressReporter | None = None,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._drain_signal = drain_signal
        self._reporter = reporter

    def claim_one(self):
        if self._drain_signal.draining:
            return None
        if not capacity.can_admit(_memory_available_bytes()):
            return None
        return super().claim_one()

    def is_exhausted(self) -> bool:
        return self._drain_signal.draining

    def on_complete(self, job_id: str, result: Any) -> None:
        if self._reporter is not None:
            self._reporter.flush(job_id)
        super().on_complete(job_id, result)

    def on_fail(self, job_id: str, error: str, retryable: bool) -> None:
        if self._reporter is not None:
            self._reporter.flush(job_id)
        super().on_fail(job_id, error, retryable)


def _coordinator_overrides_from_args(parsed_args: argparse.Namespace) -> dict[str, Any]:
    overrides: dict[str, Any] = {}
    if getattr(parsed_args, "coordinator_url", None):
        overrides["COORDINATOR_URL"] = parsed_args.coordinator_url
    if getattr(parsed_args, "token", None):
        overrides["WORKER_API_TOKEN"] = parsed_args.token
    if getattr(parsed_args, "memory_gb", None) is not None:
        overrides["WORKER_MODEL_MEMORY_BUDGET_GB"] = parsed_args.memory_gb
    return overrides


def main(args=None):
    if args is None:
        parsed_args = argparse.Namespace()
    elif isinstance(args, argparse.Namespace):
        parsed_args = args
    elif isinstance(args, dict):
        parsed_args = argparse.Namespace(**args)
    else:
        parsed_args = argparse.Namespace()

    dashboard = _dashboard_enabled(parsed_args)
    log_file = _resolve_log_file(args=parsed_args, dashboard=dashboard)
    _configure_logging(log_file=log_file, dashboard=dashboard)
    if log_file is not None:
        from worker.fleet.ollama_log import set_ollama_log_dir

        set_ollama_log_dir(log_file.parent)

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
    required = set(required_model_names())
    fleet = replace(fleet, model_count=len(required))

    job_keep_alive = resolve_job_keep_alive(fleet_keep_alive=fleet.keep_alive)
    os.environ.setdefault("AUTOANNOTATION_OLLAMA_KEEP_ALIVE", str(job_keep_alive))

    user_budget_gb = sizing.parse_model_memory_budget_gb(
        os.getenv("WORKER_MODEL_MEMORY_BUDGET_GB")
        or os.getenv("ANNOTATION_MEMORY_BUDGET_GB")
    )
    cache_budget = sizing.cache_budget_bytes(
        spec,
        user_budget_gb=user_budget_gb,
        num_servers=fleet.num_servers,
    )
    sizes = {
        name: fleet_models._model_size_bytes(name, host=None) for name in required
    }
    pack_factor = pack_factor_from_env()
    residency = select_residency_mode(
        sizes,
        cache_budget_bytes=cache_budget,
        pack_factor=pack_factor,
    )
    os.environ["OLLAMA_MAX_LOADED_MODELS"] = str(residency.max_loaded)
    log.info(
        "Residency mode=%s packed=%s/%s max_loaded=%s pack_budget=%.1f GiB keep_alive=%s",
        residency.mode,
        len(residency.packed_models),
        len(required),
        residency.max_loaded,
        residency.pack_budget_bytes / 1024**3,
        job_keep_alive,
    )

    fleet_supervisor: FleetSupervisor | None = None
    model_cache = None
    if not discover_only:
        fleet_supervisor = reset_ollama_fleet(
            fleet, spec, max_loaded=residency.max_loaded
        )
        primary_host = fleet.backend_hosts()[0]
        ensure_models(client=ollama.Client(host=primary_host))
        sizes = {
            name: fleet_models._model_size_bytes(name, host=primary_host)
            for name in required
        }
        residency = select_residency_mode(
            sizes,
            cache_budget_bytes=cache_budget,
            pack_factor=pack_factor,
        )
        if str(residency.max_loaded) != os.environ.get("OLLAMA_MAX_LOADED_MODELS"):
            os.environ["OLLAMA_MAX_LOADED_MODELS"] = str(residency.max_loaded)
            log.info(
                "Residency updated after size probe: mode=%s max_loaded=%s; restarting fleet",
                residency.mode,
                residency.max_loaded,
            )
            fleet_supervisor = reset_ollama_fleet(
                fleet, spec, max_loaded=residency.max_loaded
            )
            ensure_models(client=ollama.Client(host=primary_host))

        if residency.use_model_cache:
            model_cache, sizes = _build_model_memory_cache(
                host=primary_host,
                budget_bytes=residency.pack_budget_bytes,
                model_names=required,
                sizes=sizes,
                keep_alive=job_keep_alive,
            )
        if residency.should_prewarm:
            client = ollama.Client(host=primary_host)
            for name in sorted(required):
                client.chat(
                    model=name,
                    messages=[{"role": "user", "content": "ping"}],
                    keep_alive=job_keep_alive,
                )
        fleet = refresh_fleet_footprints(
            fleet, spec, host=primary_host, measure_runtime_peak=False,
        )
        fleet = replace(fleet, model_count=len(required))

    backends = [
        Backend(
            host=host,
            models=required,
            parallel=fleet.parallel,
        )
        for host in fleet.backend_hosts()
    ]
    router = ModelRouter(backends)
    router_thread = start_router_server(
        router,
        router_host,
        router_port,
        collect_metrics=False,
        fleet_supervisor=fleet_supervisor,
        model_cache=model_cache,
    )
    os.environ["OLLAMA_ROUTER_URL"] = f"http://{router_host}:{router_thread._port}"

    config = load_config()
    client = CoordinatorClient(config)
    worker_id = client.register()
    log.info(
        "Registered worker %s (id=%s, max_slots=%s)",
        config.worker_name,
        worker_id,
        config.max_slots,
    )

    drain_signal = _DrainSignal()
    reporter = ProgressReporter(client)
    runtime_holder: dict[str, WorkerRuntime] = {}

    def free_slots() -> int:
        runtime = runtime_holder.get("runtime")
        if runtime is None:
            return config.max_slots
        return runtime.free_slots()

    def active_jobs() -> int:
        runtime = runtime_holder.get("runtime")
        if runtime is None:
            return 0
        return len(runtime.active_jobs)

    source = _DrainAwareCoordinatorSource(
        client,
        free_slots_fn=free_slots,
        drain_signal=drain_signal,
        active_jobs_fn=active_jobs,
        reporter=reporter,
    )

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
        execute_fn=_make_execute_fn(reporter),
        heartbeat_fn=heartbeat_fn,
    )
    runtime_holder["runtime"] = runtime

    def _dashboard_meta_provider() -> dict[str, Any]:
        out: dict[str, Any] = {"slots": config.max_slots}
        if not discover_only:
            try:
                snap = residency_snapshot_from_ps(
                    fleet.backend_hosts()[0],
                    budget_bytes=residency.pack_budget_bytes,
                )
                if snap is not None:
                    out["models_in_mem"] = snap
            except Exception:
                pass
        if fleet_supervisor is not None:
            try:
                out["ollama_servers"] = fleet_supervisor.ollama_log_snapshot()
            except Exception:
                pass
        return out

    _run_with_dashboard(
        runtime,
        dashboard=dashboard,
        meta={
            "mode": "serve",
            "fleet": f"{fleet.num_servers}x{fleet.parallel}",
            "slots": config.max_slots,
            "tier": fleet.memory_tier,
        },
        meta_provider=_dashboard_meta_provider,
    )

