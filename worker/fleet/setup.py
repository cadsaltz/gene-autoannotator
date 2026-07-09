from __future__ import annotations

import logging
import os
import re
import signal
import shutil
import subprocess
import sys
import time
from pathlib import Path

from shared.env_persist import load_env_file, save_env_file
from worker.fleet import models, sizing
from worker.fleet.config import FleetConfig
from worker.fleet.sizing import DEFAULT_C_SLOT_BYTES, FleetRecommendation
from worker.probe import SystemSpec, probe_system

log = logging.getLogger(__name__)

FLEET_ENV_KEYS = (
    "OLLAMA_FLEET_SERVERS",
    "OLLAMA_FLEET_PARALLEL",
    "WORKER_MAX_SLOTS",
)


def _default_env_path() -> Path:
    return Path(os.getenv("WORKER_ENV_FILE", "worker.env"))


DEFAULT_OLLAMA_BASE_PORT = 11434
OLLAMA_PORT_SCAN_COUNT = 16


def _read_line(prompt: str) -> str:
    print(prompt, end="", flush=True)
    return sys.stdin.readline()


def _prompt_int(label: str, *, recommended: int) -> int:
    while True:
        raw = _read_line(f"Ollama {label} [recommended: {recommended}]: ").strip()
        if not raw:
            return recommended
        try:
            return int(raw)
        except ValueError:
            print("Enter an integer.", flush=True)


def validate_or_warn(spec: SystemSpec, cfg: FleetConfig) -> tuple[list[str], list[str]]:
    return sizing.validate_fleet(spec, cfg)


def prompt_fleet(spec: SystemSpec, recommendation: FleetRecommendation) -> FleetConfig:
    while True:
        n = _prompt_int("servers", recommended=recommendation.num_servers)
        p = _prompt_int("parallel per server", recommended=recommendation.parallel)
        slots = _prompt_int("max job slots", recommended=recommendation.max_slots)
        cfg = FleetConfig(
            num_servers=n,
            parallel=p,
            max_slots=slots,
            w_all_bytes=recommendation.w_all_bytes,
            c_slot_bytes=recommendation.c_slot_bytes,
        )
        errors, warnings = validate_or_warn(spec, cfg)
        for warning in warnings:
            print(f"WARNING: {warning}", flush=True)
        if errors:
            for error in errors:
                print(f"ERROR: {error}", flush=True)
            continue
        return cfg


def start_ollama_server(
    *,
    port: int,
    parallel: int,
    gpu_index: int | None,
) -> subprocess.Popen:
    env = os.environ.copy()
    env["OLLAMA_HOST"] = f"127.0.0.1:{port}"
    env["OLLAMA_NUM_PARALLEL"] = str(parallel)
    if gpu_index is not None:
        env["CUDA_VISIBLE_DEVICES"] = str(gpu_index)
    proc = subprocess.Popen(
        ["ollama", "serve"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    time.sleep(0.25)
    if proc.poll() is not None:
        stderr = (proc.stderr.read() if proc.stderr else "") or f"exit code {proc.returncode}"
        raise RuntimeError(f"ollama serve failed on port {port}: {stderr.strip()}")
    return proc


def start_fleet(cfg: FleetConfig, spec: SystemSpec) -> list[subprocess.Popen]:
    procs: list[subprocess.Popen] = []
    for i in range(cfg.num_servers):
        gpu = i % spec.gpu_count if spec.gpu_count else None
        port = cfg.base_port + i
        procs.append(
            start_ollama_server(
                port=port,
                parallel=cfg.parallel,
                gpu_index=gpu,
            )
        )
        if not _port_is_open(port):
            shutdown_fleet(procs)
            raise RuntimeError(f"Ollama server did not start listening on 127.0.0.1:{port}")
    return procs


def _find_pgrep_pids(pattern: str) -> list[int]:
    if shutil.which("pgrep") is None:
        return []
    result = subprocess.run(
        ["pgrep", "-f", pattern],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return []
    pids: list[int] = []
    for line in result.stdout.splitlines():
        token = line.strip()
        if token.isdigit():
            pids.append(int(token))
    return pids


def _find_ollama_serve_pids() -> list[int]:
    patterns = (
        "ollama serve",
        "snap/ollama",
        "ollama runner",
        "/usr/local/bin/ollama",
        "/usr/bin/ollama serve",
    )
    pids: set[int] = set()
    for pattern in patterns:
        pids.update(_find_pgrep_pids(pattern))
    return sorted(pids)


def _pids_listening_on_port(port: int) -> list[int]:
    if shutil.which("fuser") is not None:
        result = subprocess.run(
            ["fuser", f"{port}/tcp"],
            check=False,
            capture_output=True,
            text=True,
        )
        pids: list[int] = []
        for token in (result.stdout + result.stderr).replace("/", " ").split():
            if token.isdigit():
                pids.append(int(token))
        if pids:
            return sorted(set(pids))
    if shutil.which("ss") is not None:
        result = subprocess.run(
            ["ss", "-ltnp", f"sport = :{port}"],
            check=False,
            capture_output=True,
            text=True,
        )
        pids = []
        for match in re.finditer(r"pid=(\d+)", result.stdout):
            pids.append(int(match.group(1)))
        if pids:
            return sorted(set(pids))
    return []


def _stop_snap_ollama() -> None:
    if shutil.which("snap") is None:
        return
    installed = subprocess.run(
        ["snap", "list", "ollama"],
        check=False,
        capture_output=True,
        text=True,
    )
    if installed.returncode != 0:
        return
    log.info("Stopping snap ollama service")
    subprocess.run(["snap", "stop", "ollama"], check=False, capture_output=True, text=True)


def _ollama_fleet_ports(num_servers: int = 1, base_port: int = DEFAULT_OLLAMA_BASE_PORT) -> list[int]:
    return [base_port + i for i in range(max(1, num_servers))]


def kill_all_ollama_servers(*, timeout_sec: float = 10.0) -> None:
    """Stop Ollama server processes before starting a fresh fleet."""
    _stop_snap_ollama()

    ports = _ollama_fleet_ports(
        num_servers=OLLAMA_PORT_SCAN_COUNT,
        base_port=DEFAULT_OLLAMA_BASE_PORT,
    )
    pids: set[int] = set(_find_ollama_serve_pids())
    for port in ports:
        pids.update(_pids_listening_on_port(port))

    if not pids:
        return

    log.info("Stopping %s existing Ollama-related process(es)", len(pids))
    for pid in sorted(pids):
        try:
            os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            continue

    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        remaining = set(_find_ollama_serve_pids())
        for port in ports:
            remaining.update(_pids_listening_on_port(port))
        if not remaining:
            return
        time.sleep(0.1)

    remaining = set(_find_ollama_serve_pids())
    for port in ports:
        remaining.update(_pids_listening_on_port(port))
    for pid in sorted(remaining):
        try:
            os.kill(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            continue


def _port_is_open(port: int) -> bool:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.2)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def _ports_in_use(ports: list[int]) -> list[int]:
    return [port for port in ports if _port_is_open(port)]


def _ensure_ports_free(ports: list[int], *, timeout_sec: float = 10.0) -> None:
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        busy = _ports_in_use(ports)
        if not busy:
            return
        time.sleep(0.1)
    busy = _ports_in_use(ports)
    if busy:
        raise RuntimeError(
            "Ollama port(s) still in use after shutdown: "
            + ", ".join(str(port) for port in busy)
            + ". Stop the existing Ollama service manually (e.g. `snap stop ollama` "
            "or `systemctl stop ollama`) and retry."
        )


def shutdown_fleet(procs: list[subprocess.Popen]) -> None:
    for proc in procs:
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass


def reset_ollama_fleet(cfg: FleetConfig, spec: SystemSpec) -> list[subprocess.Popen]:
    """Kill any existing Ollama servers, then start a fresh fleet from config."""
    kill_all_ollama_servers()
    ports = [cfg.base_port + i for i in range(cfg.num_servers)]
    _ensure_ports_free(ports)
    return start_fleet(cfg, spec)


def _env_value(key: str, *, env_path: Path) -> str | None:
    file_values = load_env_file(env_path)
    if key in os.environ and os.environ[key]:
        return os.environ[key]
    if key in file_values and file_values[key]:
        return file_values[key]
    return None


def _fleet_env_complete(*, env_path: Path) -> bool:
    return all(_env_value(key, env_path=env_path) for key in FLEET_ENV_KEYS)


def _fleet_from_env(*, env_path: Path) -> FleetConfig | None:
    if not _fleet_env_complete(env_path=env_path):
        return None
    w_all_raw = _env_value("OLLAMA_FLEET_W_ALL_BYTES", env_path=env_path)
    c_slot_raw = _env_value("OLLAMA_FLEET_C_SLOT_BYTES", env_path=env_path)
    return FleetConfig(
        num_servers=int(_env_value("OLLAMA_FLEET_SERVERS", env_path=env_path)),
        parallel=int(_env_value("OLLAMA_FLEET_PARALLEL", env_path=env_path)),
        max_slots=int(_env_value("WORKER_MAX_SLOTS", env_path=env_path)),
        w_all_bytes=int(w_all_raw) if w_all_raw else models.estimate_w_all_bytes(),
        c_slot_bytes=int(c_slot_raw) if c_slot_raw else DEFAULT_C_SLOT_BYTES,
    )


def _persist_fleet_config(env_path: Path, cfg: FleetConfig) -> None:
    saved = load_env_file(env_path)
    saved["OLLAMA_FLEET_SERVERS"] = str(cfg.num_servers)
    saved["OLLAMA_FLEET_PARALLEL"] = str(cfg.parallel)
    saved["WORKER_MAX_SLOTS"] = str(cfg.max_slots)
    saved["OLLAMA_FLEET_W_ALL_BYTES"] = str(cfg.w_all_bytes)
    saved["OLLAMA_FLEET_C_SLOT_BYTES"] = str(cfg.c_slot_bytes)
    save_env_file(env_path, saved)


def _apply_fleet_to_environ(cfg: FleetConfig) -> None:
    os.environ["OLLAMA_FLEET_SERVERS"] = str(cfg.num_servers)
    os.environ["OLLAMA_FLEET_PARALLEL"] = str(cfg.parallel)
    os.environ["WORKER_MAX_SLOTS"] = str(cfg.max_slots)
    os.environ["OLLAMA_FLEET_W_ALL_BYTES"] = str(cfg.w_all_bytes)
    os.environ["OLLAMA_FLEET_C_SLOT_BYTES"] = str(cfg.c_slot_bytes)


def ensure_fleet_config(
    *,
    spec: SystemSpec | None = None,
    interactive: bool = True,
    env_path: Path | None = None,
) -> FleetConfig:
    path = env_path or _default_env_path()

    cfg = _fleet_from_env(env_path=path)
    if cfg is not None:
        _apply_fleet_to_environ(cfg)
        return cfg

    system_spec = spec or probe_system()
    c_slot = DEFAULT_C_SLOT_BYTES
    w_all = models.estimate_w_all_bytes()
    recommendation = sizing.recommend(
        system_spec,
        w_all_bytes=w_all,
        c_slot_bytes=c_slot,
    )

    if interactive:
        cfg = prompt_fleet(system_spec, recommendation)
    else:
        cfg = FleetConfig(
            num_servers=recommendation.num_servers,
            parallel=recommendation.parallel,
            max_slots=recommendation.max_slots,
            w_all_bytes=recommendation.w_all_bytes,
            c_slot_bytes=recommendation.c_slot_bytes,
        )

    _persist_fleet_config(path, cfg)
    _apply_fleet_to_environ(cfg)
    return cfg
