from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import ollama

from shared.job_contract import AnnotationJobRequest
from worker import executor
from worker.bootstrap import ensure_worker_env
from worker.config import load_config
from worker.fleet.models import required_model_names
from worker.fleet.setup import ensure_fleet_config, start_fleet
from worker.ollama_bootstrap import ensure_models
from worker.probe import probe_system
from worker.router import Backend, ModelRouter
from worker.router.server import start_router_server
from worker.runtime import WorkerRuntime
from worker.sources.batch import BatchJobSource


def _report_path(explicit_path: str | None) -> Path:
    if explicit_path:
        return Path(explicit_path)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return Path("reports") / f"{stamp}.json"


def _purge_llm_cache() -> None:
    cache_root = Path(os.getenv("WORKER_CACHE_DIR", "./.cache"))
    for rel in ("llm_cache", "llm_responses"):
        shutil.rmtree(cache_root / rel, ignore_errors=True)


def _execute_job(request_dict: dict[str, Any], *, job_id: str | None = None) -> dict[str, Any]:
    request = AnnotationJobRequest(**request_dict)
    return executor.run_annotation_job(request, job_id=job_id)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run worker bench batch")
    parser.add_argument("--jobs", required=True, help="JSONL file with AnnotationJobRequest per line")
    parser.add_argument("--slots", type=int, default=None, help="Override concurrent worker slots")
    parser.add_argument("--cache", choices=("cold", "warm"), default="cold")
    parser.add_argument("--report", default=None, help="Report path (default: reports/<timestamp>.json)")
    return parser.parse_args(argv)


def _shutdown_fleet(procs: list[Any]) -> None:
    for proc in procs:
        terminate = getattr(proc, "terminate", None)
        wait = getattr(proc, "wait", None)
        kill = getattr(proc, "kill", None)
        if not callable(terminate):
            continue
        try:
            terminate()
            if callable(wait):
                wait(timeout=5)
        except Exception:
            if callable(kill):
                try:
                    kill()
                except Exception:
                    pass


def main(argv=None):
    if isinstance(argv, argparse.Namespace):
        args = argv
    elif argv is None:
        args = _parse_args(None)
    else:
        args = _parse_args(list(argv))
    ensure_worker_env()
    fleet = ensure_fleet_config(interactive=False)
    spec = probe_system()
    procs = start_fleet(fleet, spec)

    if args.cache == "cold":
        _purge_llm_cache()
        os.environ.setdefault("AUTOANNOTATION_OLLAMA_KEEP_ALIVE", "5m")

    source = BatchJobSource(args.jobs)
    selected_slots = args.slots if args.slots is not None else fleet.max_slots
    runtime_fleet = replace(fleet, max_slots=selected_slots)
    required = set(required_model_names())
    backends = [
        Backend(host=host, models=required, parallel=runtime_fleet.parallel)
        for host in runtime_fleet.backend_hosts()
    ]
    router = ModelRouter(backends)
    router_thread = None
    try:
        primary_host = runtime_fleet.backend_hosts()[0]
        ensure_models(client=ollama.Client(host=primary_host))
        router_thread = start_router_server(
            router,
            "127.0.0.1",
            0,
            collect_metrics=True,
            fleet_cfg=runtime_fleet,
            jobs_submitted=source.jobs_submitted,
            model_mode=os.getenv("AUTOANNOTATION_MODEL_MODE", "performance"),
        )
        os.environ["OLLAMA_ROUTER_URL"] = f"http://127.0.0.1:{router_thread._port}"

        config = load_config()
        runtime_cfg = SimpleNamespace(
            max_slots=selected_slots,
            heartbeat_seconds=getattr(config, "heartbeat_seconds", 15),
        )
        runtime = WorkerRuntime(
            config=runtime_cfg,
            fleet_config=runtime_fleet,
            job_source=source,
            execute_fn=_execute_job,
            collect_metrics=True,
            metrics_collector=getattr(router_thread, "_metrics", None),
        )
        report = runtime.run()
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

        report_path = _report_path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        failures = int(report.get("batch", {}).get("jobs_failed", len(source.failed)))
        return 0 if failures == 0 else 1
    finally:
        if router_thread is not None:
            try:
                router_thread._server.shutdown()
                router_thread._server.server_close()
                router_thread.join(timeout=2.0)
            except Exception:
                pass
        _shutdown_fleet(procs)


if __name__ == "__main__":
    sys.exit(main())
