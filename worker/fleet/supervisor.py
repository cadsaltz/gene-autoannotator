from __future__ import annotations

import logging
import subprocess
import threading
from dataclasses import dataclass
from typing import Any

import httpx

from worker.fleet.config import FleetConfig
from worker.fleet.ollama_log import OllamaLogBuffer, get_buffer_for_port
from worker.probe import SystemSpec

log = logging.getLogger(__name__)

HEALTH_CHECK_TIMEOUT_SEC = 2.0


@dataclass
class _ManagedServer:
    host: str
    port: int
    parallel: int
    gpu_index: int | None
    max_loaded_models: int | None
    proc: subprocess.Popen | None = None
    log_buffer: OllamaLogBuffer | None = None


def _api_reachable(host: str, *, timeout_sec: float = HEALTH_CHECK_TIMEOUT_SEC) -> bool:
    try:
        response = httpx.get(f"{host.rstrip('/')}/api/tags", timeout=timeout_sec)
        return response.status_code == 200
    except Exception:
        return False


def _spawn_exit_watcher(
    host: str,
    proc: subprocess.Popen,
    *,
    log_buffer: OllamaLogBuffer | None = None,
) -> None:
    """Log when a managed Ollama child exits (OOM, segfault, etc.)."""
    if not hasattr(proc, "wait"):
        return

    def _watch() -> None:
        returncode = proc.wait()
        message = (
            f"Ollama server {host} exited unexpectedly (code={returncode}). "
            "Check dmesg/journal for OOM kills; performance models need one model "
            "in memory at a time on limited VRAM."
        )
        log.error("%s", message)
        if log_buffer is not None:
            log_buffer.append(f"*** {message} ***")

    threading.Thread(
        target=_watch,
        name=f"ollama-exit-watch-{host}",
        daemon=True,
    ).start()


class FleetSupervisor:
    """Track Ollama fleet processes and restart only when a child actually exits."""

    def __init__(self, cfg: FleetConfig, spec: SystemSpec) -> None:
        self._cfg = cfg
        self._spec = spec
        self._servers: dict[str, _ManagedServer] = {}
        self._lock = threading.Lock()

    @property
    def processes(self) -> list[subprocess.Popen]:
        return [entry.proc for entry in self._servers.values() if entry.proc is not None]

    def attach_started(
        self,
        *,
        host: str,
        port: int,
        parallel: int,
        gpu_index: int | None,
        max_loaded_models: int | None,
        proc: subprocess.Popen,
        log_buffer: OllamaLogBuffer | None = None,
    ) -> None:
        buffer = log_buffer if log_buffer is not None else get_buffer_for_port(port)
        with self._lock:
            self._servers[host] = _ManagedServer(
                host=host,
                port=port,
                parallel=parallel,
                gpu_index=gpu_index,
                max_loaded_models=max_loaded_models,
                proc=proc,
                log_buffer=buffer,
            )
        _spawn_exit_watcher(host, proc, log_buffer=buffer)

    def ollama_log_snapshot(self) -> list[dict[str, Any]]:
        """Dashboard-friendly status + recent lines for each managed server."""
        with self._lock:
            entries = list(self._servers.values())
        snapshots: list[dict[str, Any]] = []
        for entry in entries:
            proc = entry.proc
            if proc is None:
                status = "missing"
                pid = None
            elif proc.poll() is None:
                status = "running"
                pid = getattr(proc, "pid", None)
            else:
                status = "exited"
                pid = getattr(proc, "pid", None)
            buffer = entry.log_buffer or get_buffer_for_port(entry.port)
            if buffer is not None:
                snapshots.append(
                    buffer.snapshot(
                        host=entry.host,
                        port=entry.port,
                        pid=pid,
                        status=status,
                    )
                )
            else:
                snapshots.append(
                    {
                        "host": entry.host,
                        "port": entry.port,
                        "pid": pid,
                        "status": status,
                        "log_path": None,
                        "lines": [],
                        "summary": {
                            "phase": "unknown",
                            "runners": None,
                            "layers_on_gpu": None,
                            "layers_total": None,
                            "last_chat": None,
                            "alerts": [],
                        },
                    }
                )
        return snapshots

    def is_healthy(self, host: str) -> bool:
        with self._lock:
            entry = self._servers.get(host)
            if entry is None or entry.proc is None:
                return False
            if entry.proc.poll() is not None:
                return False
        return _api_reachable(host)

    def restart_if_unhealthy(self, host: str) -> bool:
        """Restart only when the managed child process has exited.

        A slow or unresponsive ``/api/tags`` during long GPU inference is normal;
        killing a busy Ollama server was a common source of mid-job failures.
        """
        with self._lock:
            entry = self._servers.get(host)
            if entry is None:
                return False
            proc_dead = entry.proc is None or entry.proc.poll() is not None

        if not proc_dead:
            if not _api_reachable(host):
                log.warning(
                    "Ollama server %s is slow to answer /api/tags but the process "
                    "is still running; not restarting (likely busy inferring)",
                    host,
                )
            return False

        log.warning("Ollama server %s process exited; restarting", host)
        with self._lock:
            entry = self._servers.get(host)
            if entry is None:
                return False
            self._restart_locked(entry)
            return True

    def shutdown(self) -> None:
        from worker.fleet.setup import shutdown_fleet

        with self._lock:
            procs = [entry.proc for entry in self._servers.values() if entry.proc is not None]
            self._servers.clear()
        shutdown_fleet(procs)

    def _restart_locked(self, entry: _ManagedServer) -> None:
        from worker.fleet.setup import (
            _ensure_ports_free,
            shutdown_fleet,
            start_ollama_server,
        )

        if entry.proc is not None:
            shutdown_fleet([entry.proc])
        _ensure_ports_free([entry.port], timeout_sec=5.0)
        entry.proc = start_ollama_server(
            port=entry.port,
            parallel=entry.parallel,
            gpu_index=entry.gpu_index,
            max_loaded_models=entry.max_loaded_models,
        )
        entry.log_buffer = get_buffer_for_port(entry.port)
        log.info("Ollama server restarted at %s", entry.host)
        _spawn_exit_watcher(entry.host, entry.proc, log_buffer=entry.log_buffer)


def attach_fleet_to_supervisor(
    supervisor: FleetSupervisor,
    cfg: FleetConfig,
    spec: SystemSpec,
    procs: list[subprocess.Popen],
) -> None:
    from worker.fleet.setup import effective_max_loaded_models

    max_loaded = effective_max_loaded_models(cfg)
    for i, proc in enumerate(procs):
        port = cfg.base_port + i
        gpu = i % spec.gpu_count if spec.gpu_count else None
        host = f"http://127.0.0.1:{port}"
        supervisor.attach_started(
            host=host,
            port=port,
            parallel=cfg.parallel,
            gpu_index=gpu,
            max_loaded_models=max_loaded,
            proc=proc,
        )
