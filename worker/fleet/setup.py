from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from shared.env_persist import load_env_file, save_env_file
from worker.fleet import models, sizing
from worker.fleet.config import FleetConfig
from worker.fleet.sizing import DEFAULT_C_SLOT_BYTES, FleetRecommendation
from worker.probe import SystemSpec, probe_system

FLEET_ENV_KEYS = (
    "OLLAMA_FLEET_SERVERS",
    "OLLAMA_FLEET_PARALLEL",
    "WORKER_MAX_SLOTS",
)


def _default_env_path() -> Path:
    return Path(os.getenv("WORKER_ENV_FILE", "worker.env"))


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
    return subprocess.Popen(["ollama", "serve"], env=env)


def start_fleet(cfg: FleetConfig, spec: SystemSpec) -> list[subprocess.Popen]:
    procs: list[subprocess.Popen] = []
    for i in range(cfg.num_servers):
        gpu = i % spec.gpu_count if spec.gpu_count else None
        procs.append(
            start_ollama_server(
                port=cfg.base_port + i,
                parallel=cfg.parallel,
                gpu_index=gpu,
            )
        )
    return procs


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
