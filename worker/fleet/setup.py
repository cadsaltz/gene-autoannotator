from __future__ import annotations

import logging
import os
import re
import signal
import shutil
import subprocess
import sys
import time
from dataclasses import replace
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
OLLAMA_SERVER_READY_TIMEOUT_SEC = 15.0
OLLAMA_SERVER_POLL_INTERVAL_SEC = 0.1

_ENV_PASSTHROUGH_KEYS = (
    "PATH",
    "HOME",
    "USER",
    "LANG",
    "LC_ALL",
    "LD_LIBRARY_PATH",
    "NVIDIA_VISIBLE_DEVICES",
    "CUDA_VISIBLE_DEVICES",
    "OLLAMA_MODELS",
    "OLLAMA_KEEP_ALIVE",
    "OLLAMA_FLASH_ATTENTION",
    "OLLAMA_LOAD_TIMEOUT",
    "OLLAMA_MAX_LOADED_MODELS",
    "OLLAMA_MAX_QUEUE",
)

# Per parallel slot. Ollama splits OLLAMA_CONTEXT_LENGTH across NUM_PARALLEL
# (n_ctx_seq = n_ctx / parallel). 8192 covers observed ~6.3k prompts + headroom.
DEFAULT_OLLAMA_SLOT_CTX = 8192


def effective_ollama_context_length(*, parallel: int) -> int:
    """Total runner ``-c`` / ``OLLAMA_CONTEXT_LENGTH`` for managed serve.

    Explicit ``OLLAMA_CONTEXT_LENGTH`` (non-zero) wins. Otherwise
    ``parallel * OLLAMA_FLEET_SLOT_CTX`` (default 8192 per slot) so prompts are
    not truncated when ``OLLAMA_NUM_PARALLEL > 1``. Larger context may spill
    layers/KV to system RAM when VRAM is tight — preferred over job failure.
    """
    raw = os.environ.get("OLLAMA_CONTEXT_LENGTH", "").strip()
    if raw and raw != "0":
        try:
            return max(1, int(raw))
        except ValueError:
            pass
    slot_raw = os.environ.get("OLLAMA_FLEET_SLOT_CTX", "").strip()
    slot = DEFAULT_OLLAMA_SLOT_CTX
    if slot_raw:
        try:
            slot = max(1, int(slot_raw))
        except ValueError:
            pass
    return max(1, parallel) * slot


def _ollama_executable() -> str:
    path = shutil.which("ollama")
    if path is None:
        raise RuntimeError("ollama executable not found on PATH")
    return path


def _ollama_is_snap() -> bool:
    path = _ollama_executable()
    return "/snap/" in path


def _ollama_serve_binary() -> str:
    """Prefer the real binary when the PATH entry is a snap wrapper."""
    path = _ollama_executable()
    if not _ollama_is_snap():
        return path
    candidates = (
        Path("/snap/ollama/current/bin/ollama"),
        Path("/snap/ollama/current/usr/bin/ollama"),
    )
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return path


def effective_max_loaded_models(cfg: FleetConfig) -> int:
    """How many models Ollama may keep resident at once.

    Default one-at-a-time (matches direct-Ollama behavior on limited VRAM).
    ``warm_stack`` tier allows all required models when they fit together.
    Explicit ``OLLAMA_MAX_LOADED_MODELS`` in the environment wins.
    """
    raw = os.environ.get("OLLAMA_MAX_LOADED_MODELS", "").strip()
    if raw:
        try:
            return max(1, int(raw))
        except ValueError:
            pass
    if cfg.memory_tier == "warm_stack" and cfg.model_count > 0:
        return cfg.model_count
    return 1


def _build_ollama_server_env(
    *,
    port: int,
    parallel: int,
    gpu_index: int | None,
    max_loaded_models: int | None = None,
) -> dict[str, str]:
    # Do not inherit OLLAMA_HOST from the parent shell/worker.env; each fleet
    # member must bind its own port explicitly.
    env: dict[str, str] = {}
    for key in _ENV_PASSTHROUGH_KEYS:
        value = os.environ.get(key)
        if value:
            env[key] = value
    env["OLLAMA_HOST"] = f"127.0.0.1:{port}"
    env["OLLAMA_NUM_PARALLEL"] = str(parallel)
    env["OLLAMA_CONTEXT_LENGTH"] = str(effective_ollama_context_length(parallel=parallel))
    if max_loaded_models is not None and max_loaded_models > 0:
        env["OLLAMA_MAX_LOADED_MODELS"] = str(max_loaded_models)
    if gpu_index is not None:
        env["CUDA_VISIBLE_DEVICES"] = str(gpu_index)
    return env


def _read_process_stderr(proc: subprocess.Popen) -> str:
    if proc.stderr is None:
        return ""
    try:
        return proc.stderr.read() or ""
    except Exception:
        return ""


def _startup_failure_detail(proc: subprocess.Popen, *, port: int) -> str:
    from worker.fleet.ollama_log import get_buffer_for_port

    buffer = get_buffer_for_port(port)
    if buffer is not None:
        recent = buffer.recent(20)
        if recent:
            return "\n".join(recent)
    stderr = _read_process_stderr(proc).strip()
    if stderr:
        return stderr
    return f"exit code {proc.returncode}"


def _wait_for_ollama_server(
    proc: subprocess.Popen,
    *,
    port: int,
    timeout_sec: float = OLLAMA_SERVER_READY_TIMEOUT_SEC,
) -> None:
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            detail = _startup_failure_detail(proc, port=port)
            raise RuntimeError(f"ollama serve failed on port {port}: {detail}")
        if _port_is_open(port):
            return
        time.sleep(OLLAMA_SERVER_POLL_INTERVAL_SEC)
    shutdown_fleet([proc])
    raise RuntimeError(
        f"Ollama server did not start listening on 127.0.0.1:{port} within {timeout_sec:.0f}s"
    )


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


def validate_or_warn(
    spec: SystemSpec,
    cfg: FleetConfig,
    *,
    model_budget_bytes: int | None = None,
) -> tuple[list[str], list[str]]:
    return sizing.validate_fleet(spec, cfg, model_budget_bytes=model_budget_bytes)


def prompt_fleet(
    spec: SystemSpec,
    recommendation: FleetRecommendation,
    *,
    model_budget_bytes: int | None = None,
) -> FleetConfig:
    for warning in recommendation.warnings:
        print(f"WARNING: {warning}", flush=True)
    print(
        f"Recommended memory tier: {recommendation.memory_tier} "
        f"(keep_alive={recommendation.keep_alive})",
        flush=True,
    )
    while True:
        n = _prompt_int("servers", recommended=recommendation.num_servers)
        p = _prompt_int("parallel per server", recommended=recommendation.parallel)
        slots = _prompt_int("max job slots", recommended=recommendation.max_slots)
        try:
            tier = sizing.classify_memory_tier(
                spec,
                w_all_bytes=recommendation.w_all_bytes,
                w_peak_bytes=recommendation.w_peak_bytes,
                c_slot_bytes=recommendation.c_slot_bytes,
                num_servers=n,
                parallel=p,
                model_budget_bytes=model_budget_bytes,
            )
        except RuntimeError as exc:
            print(f"ERROR: {exc}", flush=True)
            continue
        cfg = FleetConfig(
            num_servers=n,
            parallel=p,
            max_slots=slots,
            keep_alive=sizing.TIER_KEEP_ALIVE[tier],
            w_all_bytes=recommendation.w_all_bytes,
            w_peak_bytes=recommendation.w_peak_bytes,
            c_slot_bytes=recommendation.c_slot_bytes,
            memory_tier=tier,
        )
        errors, warnings = validate_or_warn(
            spec, cfg, model_budget_bytes=model_budget_bytes,
        )
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
    max_loaded_models: int | None = None,
) -> subprocess.Popen:
    from worker.fleet.ollama_log import (
        OllamaLogBuffer,
        ollama_server_log_path,
        register_buffer,
        start_ollama_log_tee,
    )

    env = _build_ollama_server_env(
        port=port,
        parallel=parallel,
        gpu_index=gpu_index,
        max_loaded_models=max_loaded_models,
    )
    binary = _ollama_serve_binary()
    log_path = ollama_server_log_path(port)
    log.info(
        "Starting Ollama server on 127.0.0.1:%s (binary=%s, OLLAMA_HOST=%s, "
        "parallel=%s, context_length=%s, gpu=%s, log=%s)",
        port,
        binary,
        env["OLLAMA_HOST"],
        parallel,
        env.get("OLLAMA_CONTEXT_LENGTH"),
        gpu_index,
        log_path,
    )
    buffer = OllamaLogBuffer()
    buffer.port = port
    register_buffer(port, buffer)
    proc = subprocess.Popen(
        [binary, "serve"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=0,
    )
    start_ollama_log_tee(proc, buffer, log_path)
    _wait_for_ollama_server(proc, port=port)
    return proc


def start_fleet(cfg: FleetConfig, spec: SystemSpec) -> list[subprocess.Popen]:
    procs: list[subprocess.Popen] = []
    max_loaded = effective_max_loaded_models(cfg)
    for i in range(cfg.num_servers):
        gpu = i % spec.gpu_count if spec.gpu_count else None
        port = cfg.base_port + i
        if i > 0:
            _ensure_ports_free([port], timeout_sec=5.0)
        procs.append(
            start_ollama_server(
                port=port,
                parallel=cfg.parallel,
                gpu_index=gpu,
                max_loaded_models=max_loaded,
            )
        )
    return procs


_MAX_PID_CACHE: int | None = None


def _max_pid() -> int:
    """Upper bound for valid Linux PIDs (signed 32-bit os.kill limit)."""
    global _MAX_PID_CACHE
    if _MAX_PID_CACHE is not None:
        return _MAX_PID_CACHE
    try:
        value = int(Path("/proc/sys/kernel/pid_max").read_text().strip())
    except Exception:
        value = 2**22  # common Linux default
    _MAX_PID_CACHE = value
    return value


def _coerce_pid(raw: str | int, *, exclude: set[int] | None = None) -> int | None:
    """Return a killable PID or None when the token is not a real process id."""
    try:
        pid = int(raw)
    except (TypeError, ValueError):
        return None
    # os.kill raises OverflowError for values outside signed 32-bit pid_t.
    if pid <= 0 or pid >= 2**31 or pid > _max_pid():
        return None
    if exclude and pid in exclude:
        return None
    return pid


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
    skip = {os.getpid()}
    pids: list[int] = []
    for line in result.stdout.splitlines():
        pid = _coerce_pid(line.strip(), exclude=skip)
        if pid is not None:
            pids.append(pid)
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


def _pids_from_fuser_output(text: str, *, port: int) -> list[int]:
    """Parse ``fuser`` output without treating the port itself as a PID.

    Typical stderr: ``11434/tcp:            12345 12346``
    A naive digit scan would also pick up ``11434`` (the port).
    """
    skip = {os.getpid(), port}
    pids: list[int] = []
    # Prefer the PID list after "port/proto:"
    for match in re.finditer(rf"{port}\s*/\s*tcp\s*:\s*([^\n]*)", text, flags=re.IGNORECASE):
        for token in match.group(1).split():
            pid = _coerce_pid(token.rstrip("m"), exclude=skip)  # fuser may suffix 'm'
            if pid is not None:
                pids.append(pid)
    if pids:
        return sorted(set(pids))
    # Fallback: any digit tokens, still excluding the port / our pid
    for token in text.replace("/", " ").replace(":", " ").split():
        pid = _coerce_pid(token.rstrip("m"), exclude=skip)
        if pid is not None:
            pids.append(pid)
    return sorted(set(pids))


def _pids_listening_on_port(port: int) -> list[int]:
    if shutil.which("fuser") is not None:
        result = subprocess.run(
            ["fuser", f"{port}/tcp"],
            check=False,
            capture_output=True,
            text=True,
        )
        pids = _pids_from_fuser_output(result.stdout + result.stderr, port=port)
        if pids:
            return pids
    if shutil.which("ss") is not None:
        result = subprocess.run(
            ["ss", "-ltnp", f"sport = :{port}"],
            check=False,
            capture_output=True,
            text=True,
        )
        skip = {os.getpid()}
        pids: list[int] = []
        for match in re.finditer(r"pid=(\d+)", result.stdout):
            pid = _coerce_pid(match.group(1), exclude=skip)
            if pid is not None:
                pids.append(pid)
        if pids:
            return sorted(set(pids))
    return []


def _signal_pid(pid: int, sig: int) -> None:
    try:
        os.kill(pid, sig)
    except (ProcessLookupError, PermissionError, OverflowError):
        return


def _stop_systemd_ollama() -> None:
    if shutil.which("systemctl") is None:
        return
    status = subprocess.run(
        ["systemctl", "is-active", "ollama"],
        check=False,
        capture_output=True,
        text=True,
    )
    if status.returncode != 0:
        return
    log.info("Stopping systemd ollama service")
    subprocess.run(
        ["systemctl", "stop", "ollama"],
        check=False,
        capture_output=True,
        text=True,
    )


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
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if not _pids_listening_on_port(DEFAULT_OLLAMA_BASE_PORT):
            return
        time.sleep(0.1)


def _ollama_fleet_ports(num_servers: int = 1, base_port: int = DEFAULT_OLLAMA_BASE_PORT) -> list[int]:
    return [base_port + i for i in range(max(1, num_servers))]


def kill_all_ollama_servers(*, timeout_sec: float = 10.0) -> None:
    """Stop Ollama server processes before starting a fresh fleet."""
    _stop_snap_ollama()
    _stop_systemd_ollama()

    ports = _ollama_fleet_ports(
        num_servers=OLLAMA_PORT_SCAN_COUNT,
        base_port=DEFAULT_OLLAMA_BASE_PORT,
    )
    pids: set[int] = set(_find_ollama_serve_pids())
    for port in ports:
        pids.update(_pids_listening_on_port(port))

    if not pids:
        return

    # Drop ports that looked like PIDs, our own process, and impossible values.
    self_pid = os.getpid()
    pids = {
        pid
        for pid in pids
        if _coerce_pid(pid, exclude={self_pid}) is not None
    }
    if not pids:
        return

    log.info("Stopping %s existing Ollama-related process(es)", len(pids))
    for pid in sorted(pids):
        _signal_pid(pid, signal.SIGTERM)

    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        remaining = set(_find_ollama_serve_pids())
        for port in ports:
            remaining.update(_pids_listening_on_port(port))
        remaining = {
            pid
            for pid in remaining
            if _coerce_pid(pid, exclude={self_pid}) is not None
        }
        if not remaining:
            return
        time.sleep(0.1)

    remaining = set(_find_ollama_serve_pids())
    for port in ports:
        remaining.update(_pids_listening_on_port(port))
    remaining = {
        pid
        for pid in remaining
        if _coerce_pid(pid, exclude={self_pid}) is not None
    }
    for pid in sorted(remaining):
        _signal_pid(pid, signal.SIGKILL)


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


def reset_ollama_fleet(cfg: FleetConfig, spec: SystemSpec):
    """Kill any existing Ollama servers, then start a fresh supervised fleet."""
    from worker.fleet.supervisor import FleetSupervisor, attach_fleet_to_supervisor

    kill_all_ollama_servers()
    ports = [cfg.base_port + i for i in range(cfg.num_servers)]
    _ensure_ports_free(ports)
    if cfg.num_servers > 1 and _ollama_is_snap():
        log.warning(
            "Snap Ollama detected with %s fleet servers; if startup fails, set "
            "OLLAMA_FLEET_SERVERS=1 in worker.env or install the native Ollama package.",
            cfg.num_servers,
        )
    procs = start_fleet(cfg, spec)
    supervisor = FleetSupervisor(cfg, spec)
    attach_fleet_to_supervisor(supervisor, cfg, spec, procs)
    return supervisor


def _env_value(key: str, *, env_path: Path) -> str | None:
    file_values = load_env_file(env_path)
    if key in os.environ and os.environ[key]:
        return os.environ[key]
    if key in file_values and file_values[key]:
        return file_values[key]
    return None


def _env_file_has_key(key: str, *, env_path: Path) -> bool:
    """Whether ``key`` is explicitly set in the env *file* (user intent).

    Unlike :func:`_env_value`, this ignores ``os.environ`` so that values
    auto-applied to the process env by :func:`_apply_fleet_to_environ` are
    not mistaken for an explicit user choice on a later refresh/normalize.
    """
    file_values = load_env_file(env_path)
    return bool(file_values.get(key))


def _pin_keep_alive_from_environ(env_path: Path) -> None:
    """Copy process ``OLLAMA_FLEET_KEEP_ALIVE`` into the worker env file.

    Docker ``--env-file`` / systemd ``EnvironmentFile`` inject into
    ``os.environ`` but not ``WORKER_ENV_FILE``. Without materializing the
    key, :func:`_env_file_has_key` misses the operator setting and
    :func:`_normalize_fleet_config` replaces it with the memory-tier default
    (e.g. ``vram_overflow`` → ``0``).
    """
    val = (os.environ.get("OLLAMA_FLEET_KEEP_ALIVE") or "").strip()
    if not val:
        return
    saved = load_env_file(env_path)
    if saved.get("OLLAMA_FLEET_KEEP_ALIVE") == val:
        return
    saved["OLLAMA_FLEET_KEEP_ALIVE"] = val
    save_env_file(env_path, saved)


def _fleet_env_complete(*, env_path: Path) -> bool:
    return all(_env_value(key, env_path=env_path) for key in FLEET_ENV_KEYS)


def _fleet_from_env(*, env_path: Path) -> FleetConfig | None:
    if not _fleet_env_complete(env_path=env_path):
        return None
    w_all_raw = _env_value("OLLAMA_FLEET_W_ALL_BYTES", env_path=env_path)
    w_peak_raw = _env_value("OLLAMA_FLEET_W_PEAK_BYTES", env_path=env_path)
    c_slot_raw = _env_value("OLLAMA_FLEET_C_SLOT_BYTES", env_path=env_path)
    w_all = int(w_all_raw) if w_all_raw else models.estimate_w_all_bytes()
    w_peak = int(w_peak_raw) if w_peak_raw else models.estimate_w_peak_bytes()
    tier_raw = _env_value("OLLAMA_FLEET_MEMORY_TIER", env_path=env_path)
    memory_tier: sizing.MemoryTier = "warm_stack"
    if tier_raw in sizing.TIER_KEEP_ALIVE:
        memory_tier = tier_raw  # type: ignore[assignment]
    keep_alive = (
        _env_value("OLLAMA_FLEET_KEEP_ALIVE", env_path=env_path)
        or sizing.TIER_KEEP_ALIVE[memory_tier]
    )
    return FleetConfig(
        num_servers=int(_env_value("OLLAMA_FLEET_SERVERS", env_path=env_path)),
        parallel=int(_env_value("OLLAMA_FLEET_PARALLEL", env_path=env_path)),
        max_slots=int(_env_value("WORKER_MAX_SLOTS", env_path=env_path)),
        keep_alive=keep_alive,
        w_all_bytes=w_all,
        w_peak_bytes=w_peak,
        c_slot_bytes=int(c_slot_raw) if c_slot_raw else DEFAULT_C_SLOT_BYTES,
        memory_tier=memory_tier,
        model_count=len(models.required_model_names()),
    )


def _persist_fleet_config(env_path: Path, cfg: FleetConfig) -> None:
    saved = load_env_file(env_path)
    saved["OLLAMA_FLEET_SERVERS"] = str(cfg.num_servers)
    saved["OLLAMA_FLEET_PARALLEL"] = str(cfg.parallel)
    saved["WORKER_MAX_SLOTS"] = str(cfg.max_slots)
    saved["OLLAMA_FLEET_W_ALL_BYTES"] = str(cfg.w_all_bytes)
    saved["OLLAMA_FLEET_W_PEAK_BYTES"] = str(cfg.w_peak_bytes or models.estimate_w_peak_bytes())
    saved["OLLAMA_FLEET_C_SLOT_BYTES"] = str(cfg.c_slot_bytes)
    saved["OLLAMA_FLEET_MEMORY_TIER"] = cfg.memory_tier
    saved["OLLAMA_FLEET_KEEP_ALIVE"] = cfg.keep_alive
    save_env_file(env_path, saved)


def _apply_fleet_to_environ(cfg: FleetConfig) -> None:
    os.environ["OLLAMA_FLEET_SERVERS"] = str(cfg.num_servers)
    os.environ["OLLAMA_FLEET_PARALLEL"] = str(cfg.parallel)
    os.environ["WORKER_MAX_SLOTS"] = str(cfg.max_slots)
    os.environ["OLLAMA_FLEET_W_ALL_BYTES"] = str(cfg.w_all_bytes)
    os.environ["OLLAMA_FLEET_W_PEAK_BYTES"] = str(cfg.w_peak_bytes or models.estimate_w_peak_bytes())
    os.environ["OLLAMA_FLEET_C_SLOT_BYTES"] = str(cfg.c_slot_bytes)
    os.environ["OLLAMA_FLEET_MEMORY_TIER"] = cfg.memory_tier
    os.environ["OLLAMA_FLEET_KEEP_ALIVE"] = cfg.keep_alive
    if not os.environ.get("AUTOANNOTATION_OLLAMA_KEEP_ALIVE"):
        os.environ["AUTOANNOTATION_OLLAMA_KEEP_ALIVE"] = cfg.keep_alive


def _normalize_fleet_config(
    cfg: FleetConfig,
    spec: SystemSpec,
    *,
    preserve_keep_alive: bool = False,
    model_budget_bytes: int | None = None,
) -> FleetConfig:
    w_peak = cfg.w_peak_bytes or models.estimate_w_peak_bytes()
    w_all = cfg.w_all_bytes or models.estimate_w_all_bytes()
    c_slot = cfg.c_slot_bytes or DEFAULT_C_SLOT_BYTES
    try:
        tier = sizing.classify_memory_tier(
            spec,
            w_all_bytes=w_all,
            w_peak_bytes=w_peak,
            c_slot_bytes=c_slot,
            num_servers=cfg.num_servers,
            parallel=cfg.parallel,
            model_budget_bytes=model_budget_bytes,
        )
    except RuntimeError as exc:
        log.warning(
            "Saved fleet config is infeasible (%s); applying fresh recommendation.",
            exc,
        )
        rec = sizing.recommend(
            spec,
            w_all_bytes=w_all,
            w_peak_bytes=w_peak,
            c_slot_bytes=c_slot,
            model_budget_bytes=model_budget_bytes,
        )
        keep_alive = cfg.keep_alive if preserve_keep_alive else rec.keep_alive
        return FleetConfig(
            num_servers=rec.num_servers,
            parallel=rec.parallel,
            max_slots=cfg.max_slots,
            keep_alive=keep_alive,
            w_all_bytes=rec.w_all_bytes,
            w_peak_bytes=rec.w_peak_bytes,
            c_slot_bytes=rec.c_slot_bytes,
            memory_tier=rec.memory_tier,
        )
    keep_alive = cfg.keep_alive if preserve_keep_alive else sizing.TIER_KEEP_ALIVE[tier]
    return replace(
        cfg,
        w_all_bytes=w_all,
        w_peak_bytes=w_peak,
        c_slot_bytes=c_slot,
        memory_tier=tier,
        keep_alive=keep_alive,
    )


def refresh_fleet_footprints(
    cfg: FleetConfig,
    spec: SystemSpec,
    *,
    host: str,
    measure_runtime_peak: bool = False,
    env_path: Path | None = None,
) -> FleetConfig:
    """Re-measure W_all/W_peak after Ollama is running and models are present.

    Uses manifest sizes (list/show API) by default. Set measure_runtime_peak=True
    to load every model for ``ollama ps`` VRAM measurement (slow; startup only).
    """
    w_all, w_peak, source = models.resolve_footprints(
        host=host,
        measure_runtime_peak=measure_runtime_peak,
    )
    updated = replace(
        cfg,
        w_all_bytes=w_all,
        w_peak_bytes=w_peak,
    )
    path = env_path or _default_env_path()
    preserve_ka = _env_file_has_key("OLLAMA_FLEET_KEEP_ALIVE", env_path=path)
    user_budget_gb = sizing.parse_model_memory_budget_gb(
        _env_value("WORKER_MODEL_MEMORY_BUDGET_GB", env_path=path)
        or _env_value("ANNOTATION_MEMORY_BUDGET_GB", env_path=path)
    )
    model_budget_bytes = sizing.effective_model_budget_bytes(
        spec, user_budget_gb=user_budget_gb,
    )
    updated = _normalize_fleet_config(
        updated,
        spec,
        preserve_keep_alive=preserve_ka,
        model_budget_bytes=model_budget_bytes,
    )
    _persist_fleet_config(path, updated)
    _apply_fleet_to_environ(updated)
    log.info(
        "Fleet footprints refreshed from %s: tier=%s keep_alive=%s",
        source,
        updated.memory_tier,
        updated.keep_alive,
    )
    return updated


def ensure_fleet_config(
    *,
    spec: SystemSpec | None = None,
    interactive: bool = True,
    env_path: Path | None = None,
) -> FleetConfig:
    path = env_path or _default_env_path()
    _pin_keep_alive_from_environ(path)

    cfg = _fleet_from_env(env_path=path)
    system_spec = spec or probe_system()
    user_budget_gb = sizing.parse_model_memory_budget_gb(
        _env_value("WORKER_MODEL_MEMORY_BUDGET_GB", env_path=path)
        or _env_value("ANNOTATION_MEMORY_BUDGET_GB", env_path=path)
    )
    model_budget_bytes = sizing.effective_model_budget_bytes(
        system_spec, user_budget_gb=user_budget_gb,
    )
    if cfg is not None:
        preserve_ka = _env_file_has_key("OLLAMA_FLEET_KEEP_ALIVE", env_path=path)
        cfg = _normalize_fleet_config(
            cfg,
            system_spec,
            preserve_keep_alive=preserve_ka,
            model_budget_bytes=model_budget_bytes,
        )
        errors, warnings = validate_or_warn(
            system_spec, cfg, model_budget_bytes=model_budget_bytes,
        )
        for warning in warnings:
            log.warning(warning)
        if errors:
            raise RuntimeError("; ".join(errors))
        _apply_fleet_to_environ(cfg)
        return cfg

    c_slot = DEFAULT_C_SLOT_BYTES
    w_all = models.estimate_w_all_bytes()
    w_peak = models.estimate_w_peak_bytes()
    recommendation = sizing.recommend(
        system_spec,
        w_all_bytes=w_all,
        w_peak_bytes=w_peak,
        c_slot_bytes=c_slot,
        model_budget_bytes=model_budget_bytes,
    )
    for warning in recommendation.warnings:
        log.warning(warning)
        if interactive:
            print(f"WARNING: {warning}", flush=True)

    if interactive:
        cfg = prompt_fleet(
            system_spec, recommendation, model_budget_bytes=model_budget_bytes,
        )
    else:
        cfg = FleetConfig(
            num_servers=recommendation.num_servers,
            parallel=recommendation.parallel,
            max_slots=recommendation.max_slots,
            keep_alive=recommendation.keep_alive,
            w_all_bytes=recommendation.w_all_bytes,
            w_peak_bytes=recommendation.w_peak_bytes,
            c_slot_bytes=recommendation.c_slot_bytes,
            memory_tier=recommendation.memory_tier,
        )

    _persist_fleet_config(path, cfg)
    _apply_fleet_to_environ(cfg)
    return cfg
