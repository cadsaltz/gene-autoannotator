from __future__ import annotations

import math
from dataclasses import dataclass

from worker.fleet.config import FleetConfig
from worker.probe import SystemSpec

VRAM_HEADROOM_RATIO = 0.15
MAX_PARALLEL = 16
MAX_SERVERS = 16
SUBPROCESS_OVERHEAD_BYTES = 2 * 1024**3  # Python/papers/cache per job
DEFAULT_C_SLOT_BYTES = int(0.4 * 1024**3)


@dataclass(frozen=True)
class FleetRecommendation(FleetConfig):
    warnings: tuple[str, ...] = ()


def vram_needed_bytes(num_servers: int, parallel: int, *, w_all_bytes: int, c_slot_bytes: int) -> int:
    return num_servers * (w_all_bytes + parallel * c_slot_bytes)


def enumerate_feasible(
    spec: SystemSpec,
    *,
    w_all_bytes: int,
    c_slot_bytes: int,
) -> list[FleetConfig]:
    vram_budget = int(spec.vram_total_bytes * (1 - VRAM_HEADROOM_RATIO)) if spec.vram_total_bytes else 0
    options: list[FleetConfig] = []
    for n in range(1, MAX_SERVERS + 1):
        for p in range(1, MAX_PARALLEL + 1):
            needed = vram_needed_bytes(n, p, w_all_bytes=w_all_bytes, c_slot_bytes=c_slot_bytes)
            if spec.vram_total_bytes and needed > vram_budget:
                continue
            max_slots = recommend_max_slots(spec, n, p)
            options.append(FleetConfig(num_servers=n, parallel=p, max_slots=max_slots, w_all_bytes=w_all_bytes, c_slot_bytes=c_slot_bytes))
    return options


def recommend_max_slots(spec: SystemSpec, num_servers: int, parallel: int) -> int:
    agg_lanes = num_servers * parallel
    burst_slots = max(1, math.floor(agg_lanes * 0.85))
    ram_slots = max(
        1,
        int((spec.system_ram_bytes * 0.75) // SUBPROCESS_OVERHEAD_BYTES),
    )
    cpu_slots = max(1, spec.cpu_physical)
    return min(burst_slots, ram_slots, cpu_slots)


def _score(spec: SystemSpec, cfg: FleetConfig) -> float:
    dup_penalty = max(0, cfg.num_servers - max(1, spec.gpu_count)) * cfg.w_all_bytes
    return cfg.agg_lanes + 0.3 * cfg.parallel * min(cfg.num_servers, max(1, spec.gpu_count)) - 0.5 * (dup_penalty / max(spec.vram_total_bytes, 1))


def recommend(spec: SystemSpec, *, w_all_bytes: int, c_slot_bytes: int) -> FleetRecommendation:
    feasible = enumerate_feasible(spec, w_all_bytes=w_all_bytes, c_slot_bytes=c_slot_bytes)
    if not feasible:
        raise RuntimeError("No feasible Ollama fleet configuration for this machine")
    best = max(feasible, key=lambda cfg: _score(spec, cfg))
    warnings: list[str] = []
    if spec.gpu_count == 1 and best.num_servers > 1:
        warnings.append(
            f"{best.num_servers} Ollama servers on 1 GPU duplicates model weights; prefer fewer servers with higher parallel when possible."
        )
    if best.max_slots > best.agg_lanes:
        warnings.append("max_slots exceeds aggregation lanes; expect end-of-batch stalls.")
    return FleetRecommendation(
        num_servers=best.num_servers,
        parallel=best.parallel,
        max_slots=best.max_slots,
        w_all_bytes=w_all_bytes,
        c_slot_bytes=c_slot_bytes,
        warnings=tuple(warnings),
    )


def validate_fleet(spec: SystemSpec, cfg: FleetConfig) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    if spec.vram_total_bytes:
        needed = vram_needed_bytes(cfg.num_servers, cfg.parallel, w_all_bytes=cfg.w_all_bytes, c_slot_bytes=cfg.c_slot_bytes)
        budget = int(spec.vram_total_bytes * (1 - VRAM_HEADROOM_RATIO))
        if needed > budget:
            errors.append(f"VRAM exceeded: need {needed / 1024**3:.1f} GB, budget {budget / 1024**3:.1f} GB")
    if spec.gpu_count == 1 and cfg.num_servers > 1:
        warnings.append("Multiple Ollama servers on one GPU duplicate weights.")
    if cfg.max_slots > cfg.agg_lanes:
        warnings.append(f"{cfg.max_slots} slots > {cfg.agg_lanes} aggregation lanes.")
    if cfg.num_servers > MAX_SERVERS or cfg.parallel > MAX_PARALLEL:
        errors.append("Requested fleet exceeds policy maximum.")
    return errors, warnings
