from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import signal
import sys
import threading
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import ollama

from shared.job_contract import AnnotationJobRequest
from worker import executor
from worker.bench_dashboard import BenchDashboard
from worker.bootstrap import ensure_worker_env
from worker.config import load_config
from worker.fleet.models import required_model_names
from worker.fleet.setup import ensure_fleet_config, refresh_fleet_footprints, reset_ollama_fleet
from worker.fleet.supervisor import FleetSupervisor
from worker.ollama_bootstrap import ensure_models, models_loaded
from worker.probe import probe_system
from worker.fleet import models as fleet_models
from worker.fleet import sizing
from worker.router import Backend, ModelRouter
from worker.router import ollama_http
from worker.router.model_cache import ModelMemoryCache
from worker.router.ollama_ps import residency_snapshot_from_ps
from worker.router.residency import (
    effective_residency_sizes,
    pack_factor_from_env,
    runtime_inflate_from_env,
    select_residency_mode,
)
from worker.router.server import start_router_server, stop_router_server
from worker.runtime import WorkerRuntime
from worker.sources.batch import BatchJobSource

DEFAULT_LOG_FILENAME = "worker-bench.log"

log = logging.getLogger(__name__)

_interrupt_count = 0
_runtime_for_shutdown: WorkerRuntime | None = None


def _build_model_memory_cache(
    *,
    host: str,
    budget_bytes: int,
    model_names: set[str] | list[str],
    sizes: dict[str, int] | None = None,
    keep_alive: int | str = "5m",
) -> tuple[ModelMemoryCache, dict[str, int]]:
    resolved_sizes = sizes or {
        name: fleet_models._model_size_bytes(name, host=host) for name in model_names
    }

    def load_fn(h: str, model: str) -> None:
        ollama_http.chat(
            h,
            model=model,
            messages=[{"role": "user", "content": "ping"}],
            keep_alive=keep_alive,
        )

    cache = ModelMemoryCache(
        host=host,
        budget_bytes=budget_bytes,
        model_sizes=resolved_sizes,
        unload_fn=ollama_http.unload_model,
        load_fn=load_fn,
    )
    return cache, resolved_sizes


def configure_bench_logging(*, log_file: Path | None = None, dashboard: bool = False) -> None:
    """Configure root logging for bench runs.

    When `dashboard` is active and a log file is available, verbose logs go
    only to that file so they don't corrupt the in-place `rich.Live` render.
    Otherwise (or with no log file), logs stream to stdout as before, with
    an optional file handler alongside for `--log-file`.
    """
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.DEBUG if dashboard else logging.INFO)

    if dashboard and log_file is not None:
        root.addHandler(_file_handler(log_file))
        return

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s | %(message)s"))
    root.addHandler(stream_handler)

    if log_file is not None:
        root.addHandler(_file_handler(log_file))


def _file_handler(log_file: Path) -> logging.Handler:
    log_file = Path(log_file)
    log_file.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(log_file, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s | %(message)s"))
    return handler


def _dashboard_enabled(args: argparse.Namespace) -> bool:
    no_dashboard = bool(getattr(args, "no_dashboard", False))
    env_flag = os.getenv("WORKER_BENCH_DASHBOARD", "1")
    return sys.stdout.isatty() and not no_dashboard and env_flag != "0"


def _resolve_log_file(
    *,
    args: argparse.Namespace,
    dashboard: bool,
    report_path: Path,
) -> Path | None:
    explicit = getattr(args, "log_file", None) or os.getenv("WORKER_LOG_FILE")
    if explicit:
        return Path(explicit)
    if not dashboard:
        return None
    output_dir = getattr(args, "output_dir", None)
    if output_dir:
        # Inside the mounted output dir so Docker --rm does not discard logs.
        return Path(output_dir).expanduser().resolve() / DEFAULT_LOG_FILENAME
    return report_path.parent / DEFAULT_LOG_FILENAME


def _progress(message: str) -> None:
    print(message, flush=True)
    log.info(message)


def _report_path(explicit_path: str | None) -> Path:
    if explicit_path:
        return Path(explicit_path)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return Path("reports") / f"{stamp}.json"


def _purge_llm_cache() -> None:
    cache_root = Path(os.getenv("WORKER_CACHE_DIR", "./.cache"))
    for rel in ("llm_cache", "llm_responses"):
        shutil.rmtree(cache_root / rel, ignore_errors=True)


def _execute_job(
    request_dict: dict[str, Any],
    *,
    job_id: str | None = None,
    on_progress=None,
) -> dict[str, Any]:
    request = AnnotationJobRequest(**request_dict)
    return executor.run_annotation_job(request, job_id=job_id, on_progress=on_progress)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run worker bench batch")
    parser.add_argument("--jobs", required=True, help="JSONL file with AnnotationJobRequest per line")
    parser.add_argument("--slots", type=int, default=None, help="Override concurrent worker slots")
    parser.add_argument("--cache", choices=("cold", "warm"), default="cold")
    parser.add_argument("--report", default=None, help="Report path (default: reports/<timestamp>.json)")
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Directory for annotation JSON outputs (sets WORKER_OUTPUT_DIR; local disk only)",
    )
    parser.add_argument(
        "--keep-alive",
        default=None,
        help=(
            "Ollama keep_alive for all LLM calls. When omitted, uses "
            "OLLAMA_FLEET_KEEP_ALIVE / AUTOANNOTATION_OLLAMA_KEEP_ALIVE from the "
            "worker env (same source as other fleet options). Examples: -1, 5m, 0."
        ),
    )
    parser.add_argument(
        "--no-warm-models",
        action="store_true",
        help="Skip pre-loading all required models before the batch.",
    )
    parser.add_argument(
        "--configure-fleet",
        action="store_true",
        help=(
            "Prompt for Ollama fleet settings (servers, parallel, slots) instead of "
            "using saved or recommended values. Requires an interactive terminal."
        ),
    )
    parser.add_argument(
        "--no-dashboard",
        action="store_true",
        help="Disable the live in-place dashboard even on a TTY; use linear logs instead.",
    )
    parser.add_argument(
        "--log-file",
        default=None,
        help=(
            "Write verbose logs to this file (default: alongside --report, or "
            "WORKER_LOG_FILE, when the dashboard is active)."
        ),
    )
    return parser.parse_args(argv)


def _shutdown_fleet(supervisor: FleetSupervisor | None) -> None:
    if supervisor is not None:
        supervisor.shutdown()


def _apply_output_dir(output_dir: str | None) -> None:
    if not output_dir:
        return
    path = Path(output_dir).expanduser().resolve()
    path.mkdir(parents=True, exist_ok=True)
    os.environ["WORKER_OUTPUT_DIR"] = str(path)


def _run_with_dashboard(
    runtime: WorkerRuntime,
    *,
    dashboard: bool,
    meta: dict[str, Any],
    meta_provider: Any | None = None,
) -> dict[str, Any] | None:
    if not dashboard:
        return runtime.run()

    # Blank line between setup logs and the live dashboard panel.
    print(flush=True)
    stop_event = threading.Event()
    dashboard_thread = threading.Thread(
        target=BenchDashboard().run_live,
        args=(runtime, stop_event),
        kwargs={"meta": meta, "meta_provider": meta_provider},
        name="worker-bench-dashboard",
        daemon=True,
    )
    dashboard_thread.start()
    try:
        return runtime.run()
    finally:
        stop_event.set()
        dashboard_thread.join(timeout=5)


def _install_shutdown_handlers(runtime: WorkerRuntime) -> None:
    global _runtime_for_shutdown
    _runtime_for_shutdown = runtime

    def _handle_shutdown(signum, frame) -> None:
        global _interrupt_count
        _interrupt_count += 1
        if _interrupt_count == 1:
            _progress("Shutdown requested (Ctrl+C); stopping jobs and cleaning up...")
            if _runtime_for_shutdown is not None:
                _runtime_for_shutdown.request_shutdown()
            return
        _progress("Force shutdown.")
        executor.terminate_active_jobs()
        os._exit(130)

    signal.signal(signal.SIGINT, _handle_shutdown)
    signal.signal(signal.SIGTERM, _handle_shutdown)


def main(argv=None):
    if isinstance(argv, argparse.Namespace):
        args = argv
    elif argv is None:
        args = _parse_args(None)
    else:
        args = _parse_args(list(argv))

    dashboard = _dashboard_enabled(args)
    report_path = _report_path(getattr(args, "report", None))
    log_file = _resolve_log_file(args=args, dashboard=dashboard, report_path=report_path)
    configure_bench_logging(log_file=log_file, dashboard=dashboard)
    if log_file is not None:
        from worker.fleet.ollama_log import set_ollama_log_dir

        set_ollama_log_dir(log_file.parent)

    configure_fleet = bool(getattr(args, "configure_fleet", False))
    if configure_fleet and not sys.stdin.isatty():
        print(
            "Error: --configure-fleet requires an interactive terminal.",
            file=sys.stderr,
            flush=True,
        )
        return 2
    if not os.getenv("WORKER_ENV_FILE"):
        os.environ["WORKER_ENV_FILE"] = str(
            Path(os.getenv("WORKER_OUTPUT_DIR", "/tmp")) / "worker.env"
        )
    ensure_worker_env(
        interactive=False,
        skip_fleet_config=configure_fleet,
        require_coordinator=False,
    )
    fleet = ensure_fleet_config(interactive=configure_fleet)
    spec = probe_system()
    if getattr(args, "output_dir", None):
        _apply_output_dir(args.output_dir)
        _progress(f"Annotation output directory: {os.environ['WORKER_OUTPUT_DIR']}")

    model_mode = os.getenv("AUTOANNOTATION_MODEL_MODE", "performance")
    required = set(required_model_names())
    fleet = replace(fleet, model_count=len(required))

    from worker.ollama_keep_alive import resolve_job_keep_alive

    job_keep_alive = resolve_job_keep_alive(
        cli_value=getattr(args, "keep_alive", None),
        fleet_keep_alive=fleet.keep_alive,
    )
    os.environ["AUTOANNOTATION_OLLAMA_KEEP_ALIVE"] = str(job_keep_alive)
    os.environ["OLLAMA_FLEET_KEEP_ALIVE"] = str(job_keep_alive)
    fleet = replace(fleet, keep_alive=str(job_keep_alive))

    user_budget_gb = sizing.parse_model_memory_budget_gb(
        os.getenv("WORKER_MODEL_MEMORY_BUDGET_GB")
        or os.getenv("ANNOTATION_MEMORY_BUDGET_GB")
    )
    cache_budget = sizing.cache_budget_bytes(
        spec,
        user_budget_gb=user_budget_gb,
        num_servers=fleet.num_servers,
    )
    # Size probe before fleet start (local/manifest estimates) so MAX_LOADED
    # is applied when ollama serve launches. Inflate weights toward loaded
    # footprint (KV/runtime); manifest sizes alone under-admit on overflow boxes.
    weight_sizes = {
        name: fleet_models._model_size_bytes(name, host=None) for name in required
    }
    pack_factor = pack_factor_from_env()
    runtime_inflate = runtime_inflate_from_env()
    sizes = effective_residency_sizes(
        weight_sizes,
        inflate=runtime_inflate,
        parallel=fleet.parallel,
        c_slot_bytes=fleet.c_slot_bytes,
    )
    residency = select_residency_mode(
        sizes,
        cache_budget_bytes=cache_budget,
        pack_factor=pack_factor,
    )
    os.environ["OLLAMA_MAX_LOADED_MODELS"] = str(residency.max_loaded)

    _progress(
        f"Bench setup: model_mode={model_mode}, fleet={fleet.num_servers}x"
        f"parallel={fleet.parallel}, slots={args.slots if args.slots is not None else fleet.max_slots}, "
        f"memory_tier={fleet.memory_tier}, models={len(required)}, "
        f"ollama_gate={fleet.parallel}/server"
    )
    _progress(
        f"Residency mode={residency.mode} packed={len(residency.packed_models)}/"
        f"{len(required)} max_loaded={residency.max_loaded} "
        f"cache_budget={cache_budget / 1024**3:.1f} GiB "
        f"pack_budget={residency.pack_budget_bytes / 1024**3:.1f} GiB "
        f"(factor={pack_factor:.2f} inflate={runtime_inflate:.2f} "
        f"c_slot={fleet.c_slot_bytes / 1024**3:.2f} GiB×{fleet.parallel}) "
        f"keep_alive={job_keep_alive}"
    )
    _progress("Resetting Ollama fleet (stop existing servers, start fresh)...")
    fleet_supervisor: FleetSupervisor | None = None
    fleet_supervisor = reset_ollama_fleet(
        fleet, spec, max_loaded=residency.max_loaded
    )
    _progress(
        f"Ollama fleet listening on {', '.join(fleet.backend_hosts())}"
    )

    if args.cache == "cold":
        _purge_llm_cache()
        _progress("LLM cache cleared (cold start)")

    source = BatchJobSource(args.jobs)
    selected_slots = args.slots if args.slots is not None else fleet.max_slots
    runtime_fleet = replace(fleet, max_slots=selected_slots)
    backends = [
        Backend(
            host=host,
            models=required,
            parallel=runtime_fleet.parallel,
        )
        for host in runtime_fleet.backend_hosts()
    ]
    router = ModelRouter(backends)
    router_thread = None
    try:
        primary_host = runtime_fleet.backend_hosts()[0]
        _progress(f"Ensuring models are available on {primary_host}...")
        pulled = ensure_models(client=ollama.Client(host=primary_host))
        if pulled:
            _progress(f"Pulled {len(pulled)} model(s): {', '.join(pulled)}")
        else:
            _progress("All required models already present")

        # Refresh sizes from the live fleet host and re-select if needed.
        weight_sizes = {
            name: fleet_models._model_size_bytes(name, host=primary_host)
            for name in required
        }
        sizes = effective_residency_sizes(
            weight_sizes,
            inflate=runtime_inflate,
            parallel=fleet.parallel,
            c_slot_bytes=fleet.c_slot_bytes,
        )
        residency = select_residency_mode(
            sizes,
            cache_budget_bytes=cache_budget,
            pack_factor=pack_factor,
        )
        if str(residency.max_loaded) != os.environ.get("OLLAMA_MAX_LOADED_MODELS"):
            os.environ["OLLAMA_MAX_LOADED_MODELS"] = str(residency.max_loaded)
            _progress(
                f"Residency updated after size probe: mode={residency.mode} "
                f"max_loaded={residency.max_loaded}; restarting fleet..."
            )
            fleet_supervisor = reset_ollama_fleet(
                fleet, spec, max_loaded=residency.max_loaded
            )
            ensure_models(client=ollama.Client(host=primary_host))

        model_cache = None
        if residency.use_model_cache:
            model_cache, sizes = _build_model_memory_cache(
                host=primary_host,
                budget_bytes=residency.pack_budget_bytes,
                model_names=required,
                sizes=sizes,
                keep_alive=job_keep_alive,
            )

        if residency.should_prewarm and not args.no_warm_models:
            _progress(
                f"Pre-warming all {len(required)} model(s) "
                f"(warm_stack, keep_alive={job_keep_alive})..."
            )
            client = ollama.Client(host=primary_host)
            for name in sorted(required):
                client.chat(
                    model=name,
                    messages=[{"role": "user", "content": "ping"}],
                    keep_alive=job_keep_alive,
                )
            missing = models_loaded(client=client, required=sorted(required))
            if missing:
                _progress(
                    f"Warning: after pre-warm, not all models resident: "
                    f"{', '.join(missing)}"
                )
            else:
                _progress("All models loaded (warm_stack)")
        elif residency.mode == "single":
            _progress(
                "Residency single: MAX_LOADED=1, load on demand "
                "(same-model parallel still allowed)"
            )
        elif residency.use_model_cache:
            _progress(
                f"Model cache on: pack_budget="
                f"{residency.pack_budget_bytes / 1024**3:.1f} GiB, "
                f"packed={', '.join(residency.packed_models)}"
            )
        else:
            _progress("Skipping pre-warm (disabled or not warm_stack)")

        fleet = refresh_fleet_footprints(
            fleet, spec, host=primary_host, measure_runtime_peak=False,
        )
        runtime_fleet = replace(fleet, max_slots=selected_slots, model_count=len(required))
        chat_timeout = os.getenv("OLLAMA_CHAT_TIMEOUT_SEC")
        timeout_note = (
            f"{chat_timeout}s"
            if chat_timeout and str(chat_timeout).strip() not in {"0", "none", "off"}
            else "unlimited"
        )
        _progress(
            f"Model footprints: W_all={fleet.w_all_bytes / (1024**3):.2f} GB, "
            f"W_peak={fleet.w_peak_bytes / (1024**3):.2f} GB, "
            f"tier={fleet.memory_tier}, job_keep_alive={job_keep_alive}, "
            f"residency={residency.mode}, "
            f"pack_budget={residency.pack_budget_bytes / 1024**3:.1f} GiB, "
            f"ollama_chat_timeout={timeout_note}"
        )
        router_thread = start_router_server(
            router,
            "127.0.0.1",
            0,
            collect_metrics=True,
            log_requests=True,
            fleet_cfg=runtime_fleet,
            fleet_supervisor=fleet_supervisor,
            jobs_submitted=source.jobs_submitted,
            model_mode=model_mode,
            model_cache=model_cache,
        )
        os.environ["OLLAMA_ROUTER_URL"] = f"http://127.0.0.1:{router_thread._port}"
        _progress(f"Model router ready at {os.environ['OLLAMA_ROUTER_URL']}")

        config = load_config()
        runtime_cfg = SimpleNamespace(
            max_slots=selected_slots,
            heartbeat_seconds=getattr(config, "heartbeat_seconds", 15),
        )
        _progress(
            f"Running {source.jobs_submitted} job(s) with {selected_slots} concurrent slot(s)..."
        )
        runtime = WorkerRuntime(
            config=runtime_cfg,
            fleet_config=runtime_fleet,
            job_source=source,
            execute_fn=_execute_job,
            collect_metrics=True,
            metrics_collector=getattr(router_thread, "_metrics", None),
        )
        _install_shutdown_handlers(runtime)

        def _dashboard_meta_provider() -> dict[str, Any]:
            out: dict[str, Any] = {"slots": selected_slots}
            try:
                if model_cache is not None:
                    # Cache mode: residency is local bookkeeping — no /api/ps.
                    snap = model_cache.residency_snapshot()
                    flight = router.in_flight_by_model()
                    for row in snap.get("models") or []:
                        if isinstance(row, dict) and isinstance(row.get("model"), str):
                            row["in_flight"] = int(flight.get(row["model"], row.get("in_flight") or 0))
                    out["models_in_mem"] = snap
                else:
                    snap = residency_snapshot_from_ps(
                        primary_host,
                        budget_bytes=residency.pack_budget_bytes,
                        in_flight=router.in_flight_by_model(),
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

        report = _run_with_dashboard(
            runtime,
            dashboard=dashboard,
            meta={
                "mode": "bench",
                "fleet": f"{runtime_fleet.num_servers}x{runtime_fleet.parallel}",
                "slots": selected_slots,
                "tier": runtime_fleet.memory_tier,
            },
            meta_provider=_dashboard_meta_provider,
        )
        if runtime.shutdown_requested:
            _progress("Bench interrupted.")
            return 130
        if report is None:
            metrics = getattr(router_thread, "_metrics", None)
            if metrics is None:
                report = {
                    "batch": {
                        "jobs_submitted": source.jobs_submitted,
                        "jobs_completed": len(source.completed),
                        "jobs_failed": len(source.failed),
                        "jobs_per_hour": 0.0,
                    }
                }
            else:
                report = metrics.build_report(
                    fleet_cfg=runtime_fleet,
                    jobs_submitted=source.jobs_submitted,
                    model_mode=os.getenv("AUTOANNOTATION_MODEL_MODE", "performance"),
                )

        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        batch = report.get("batch", {})
        _progress(
            f"Bench complete: {batch.get('jobs_completed', 0)}/{batch.get('jobs_submitted', 0)} "
            f"jobs, jobs_per_hour={batch.get('jobs_per_hour', 0):.2f}, "
            f"report={report_path}"
        )
        failures = int(report.get("batch", {}).get("jobs_failed", len(source.failed)))
        return 0 if failures == 0 else 1
    finally:
        if router_thread is not None:
            try:
                stop_router_server(router_thread)
            except Exception:
                pass
        _shutdown_fleet(fleet_supervisor)


if __name__ == "__main__":
    sys.exit(main())
