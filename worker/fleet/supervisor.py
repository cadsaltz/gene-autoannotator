from __future__ import annotations

import logging
import subprocess
import threading
from dataclasses import dataclass

import httpx

from worker.fleet.config import FleetConfig
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


def _api_reachable(host: str, *, timeout_sec: float = HEALTH_CHECK_TIMEOUT_SEC) -> bool:
    try:
        response = httpx.get(f"{host.rstrip('/')}/api/tags", timeout=timeout_sec)
        return response.status_code == 200
    except Exception:
        return False


class FleetSupervisor:
    """Track Ollama fleet processes and restart crashed or unresponsive servers."""

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
    ) -> None:
        with self._lock:
            self._servers[host] = _ManagedServer(
                host=host,
                port=port,
                parallel=parallel,
                gpu_index=gpu_index,
                max_loaded_models=max_loaded_models,
                proc=proc,
            )

    def is_healthy(self, host: str) -> bool:
        with self._lock:
            entry = self._servers.get(host)
            if entry is None or entry.proc is None:
                return False
            if entry.proc.poll() is not None:
                return False
        return _api_reachable(host)

    def restart_if_unhealthy(self, host: str) -> bool:
        """Restart the server for ``host`` when the process exited or API is down."""
        with self._lock:
            entry = self._servers.get(host)
            if entry is None:
                return False
            proc_dead = entry.proc is None or entry.proc.poll() is not None
        if not proc_dead and _api_reachable(host):
            return False

        log.warning("Ollama server %s unhealthy; restarting", host)
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
        log.info("Ollama server restarted at %s", entry.host)


def attach_fleet_to_supervisor(
    supervisor: FleetSupervisor,
    cfg: FleetConfig,
    spec: SystemSpec,
    procs: list[subprocess.Popen],
) -> None:
    max_loaded = cfg.model_count if cfg.model_count > 0 else None
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
