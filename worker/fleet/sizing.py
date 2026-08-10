from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from worker.fleet.config import FleetConfig
from worker.fleet.models import required_model_names
from worker.probe import SystemSpec

VRAM_HEADROOM_RATIO = 0.15
RAM_MODEL_RATIO = 0.50
MAX_PARALLEL = 16
MAX_SERVERS = 16
SUBPROCESS_OVERHEAD_BYTES = 2 * 1024**3  # Python/papers/cache per job
DEFAULT_C_SLOT_BYTES = int(0.4 * 1024**3)

MemoryTier = Literal["warm_stack", "swap", "vram_overflow"]

TIER_KEEP_ALIVE: dict[MemoryTier, str] = {
    "warm_stack": "5m",
    "swap": "0",
    "vram_overflow": "0",
}


@dataclass(frozen=True)
class FleetRecommendation(FleetConfig):
    memory_tier: MemoryTier = "warm_stack"
    w_peak_bytes: int = 0
    warnings: tuple[str, ...] = ()


def vram_needed_bytes(
    num_servers: int,
    parallel: int,
    *,
    model_bytes: int,
    c_slot_bytes: int,
) -> int:
    return num_servers * (model_bytes + parallel * c_slot_bytes)


def vram_budget_for_fleet(spec: SystemSpec, num_servers: int) -> int:
    if not spec.vram_total_bytes:
        return 0
    per_gpu = [
        int(vram * (1 - VRAM_HEADROOM_RATIO)) for vram in spec.vram_bytes
    ]
    gpu_count = max(1, spec.gpu_count)
    if num_servers <= gpu_count:
        return sum(per_gpu[i % gpu_count] for i in range(num_servers))
    return sum(per_gpu)


def ram_model_budget_bytes(spec: SystemSpec) -> int:
    if spec.system_ram_bytes <= 0:
        return 0
    return int(spec.system_ram_bytes * RAM_MODEL_RATIO)


def total_model_budget_bytes(spec: SystemSpec, num_servers: int) -> int:
    return vram_budget_for_fleet(spec, num_servers) + ram_model_budget_bytes(spec)


def machine_model_cap_bytes(spec: SystemSpec, num_servers: int = 1) -> int:
    return total_model_budget_bytes(spec, num_servers)


def parse_model_memory_budget_gb(raw: str | None) -> float | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text or text == "-1":
        return None
    value = float(text)
    if value <= 0:
        # "0" (and any negative other than the "-1" sentinel above) has no
        # sensible meaning as a model-memory budget; treat as unset/max
        # rather than silently clamping the fleet to zero bytes.
        return None
    return value


def effective_model_budget_bytes(
    spec: SystemSpec,
    *,
    user_budget_gb: float | None,
    num_servers: int = 1,
) -> int:
    cap = machine_model_cap_bytes(spec, num_servers)
    if user_budget_gb is None or user_budget_gb < 0:
        return cap
    user_bytes = int(user_budget_gb * 1024**3)
    if cap <= 0:
        # Probe couldn't determine machine capacity; don't let a bogus
        # non-positive cap clamp an explicit positive user budget to 0.
        return user_bytes
    return min(user_bytes, cap)


def _budget_with_user_cap(
    machine_budget: int,
    model_budget_bytes: int | None,
) -> int:
    if model_budget_bytes is None:
        return machine_budget
    if machine_budget <= 0 and model_budget_bytes > 0:
        return model_budget_bytes
    return min(machine_budget, model_budget_bytes)


def _feasibility_budget_bytes(
    spec: SystemSpec,
    num_servers: int,
    *,
    tier: MemoryTier,
    model_budget_bytes: int | None,
) -> int:
    if tier == "warm_stack":
        base = vram_budget_for_fleet(spec, num_servers)
    else:
        base = total_model_budget_bytes(spec, num_servers)
    return _budget_with_user_cap(base, model_budget_bytes)


def classify_memory_tier(
    spec: SystemSpec,
    *,
    w_all_bytes: int,
    w_peak_bytes: int,
    c_slot_bytes: int,
    num_servers: int = 1,
    parallel: int = 1,
    model_budget_bytes: int | None = None,
) -> MemoryTier:
    vram_budget = vram_budget_for_fleet(spec, num_servers)
    machine_cap = total_model_budget_bytes(spec, num_servers)
    total_budget = _budget_with_user_cap(machine_cap, model_budget_bytes)
    warm_need = vram_needed_bytes(
        num_servers, parallel, model_bytes=w_all_bytes, c_slot_bytes=c_slot_bytes,
    )
    peak_need = vram_needed_bytes(
        num_servers, parallel, model_bytes=w_peak_bytes, c_slot_bytes=c_slot_bytes,
    )

    def _within_user_budget(need: int) -> bool:
        return model_budget_bytes is None or need <= model_budget_bytes

    if vram_budget and warm_need <= vram_budget and _within_user_budget(warm_need):
        return "warm_stack"
    if vram_budget and peak_need <= vram_budget and _within_user_budget(peak_need):
        return "swap"
    if peak_need <= total_budget:
        return "vram_overflow"

    budget_is_binding = (
        model_budget_bytes is not None
        and (machine_cap <= 0 or model_budget_bytes < machine_cap)
    )
    if budget_is_binding:
        raise RuntimeError(
            "No feasible Ollama fleet configuration within your "
            "WORKER_MODEL_MEMORY_BUDGET_GB budget: largest model footprint needs "
            f"{peak_need / 1024**3:.1f} GB but the configured budget allows only "
            f"{model_budget_bytes / 1024**3:.1f} GB (this machine's VRAM+RAM capacity is "
            f"{machine_cap / 1024**3:.1f} GB). Raise WORKER_MODEL_MEMORY_BUDGET_GB or set it "
            "to -1 to use the full machine capacity."
        )
    raise RuntimeError(
        "No feasible Ollama fleet configuration for this machine: "
        f"largest model footprint needs {peak_need / 1024**3:.1f} GB "
        f"(VRAM+RAM budget {total_budget / 1024**3:.1f} GB)"
    )


def tier_warnings(
    tier: MemoryTier,
    *,
    w_all_bytes: int,
    w_peak_bytes: int,
    spec: SystemSpec,
    num_servers: int,
) -> list[str]:
    warnings: list[str] = []
    if tier == "swap":
        warnings.append(
            "All models do not fit in VRAM simultaneously; using keep_alive=0 and "
            "loading one model per request."
        )
    elif tier == "vram_overflow":
        warnings.append(
            f"Largest model ({w_peak_bytes / 1024**3:.1f} GB) exceeds VRAM; Ollama will "
            "spill layers into system RAM. Expect much slower inference."
        )
    if spec.gpu_count == 1 and num_servers > 1:
        warnings.append(
            f"{num_servers} Ollama servers on 1 GPU duplicate weights and reduce "
            "throughput; prefer 1 server with higher parallel."
        )
    if tier != "warm_stack" and w_all_bytes > w_peak_bytes:
        warnings.append(
            f"Warm-stack footprint is {w_all_bytes / 1024**3:.1f} GB but only "
            f"{w_peak_bytes / 1024**3:.1f} GB peak is budgeted per request."
        )
    return warnings


def _max_servers_for_spec(spec: SystemSpec) -> int:
    if spec.gpu_count > 0:
        return min(MAX_SERVERS, spec.gpu_count)
    return MAX_SERVERS


def enumerate_feasible(
    spec: SystemSpec,
    *,
    w_all_bytes: int,
    w_peak_bytes: int,
    c_slot_bytes: int,
    model_budget_bytes: int | None = None,
) -> list[tuple[FleetConfig, MemoryTier]]:
    max_servers = _max_servers_for_spec(spec)
    options: list[tuple[FleetConfig, MemoryTier]] = []

    for n in range(1, max_servers + 1):
        tier_for_cap: MemoryTier | None = None
        try:
            tier_for_cap = classify_memory_tier(
                spec,
                w_all_bytes=w_all_bytes,
                w_peak_bytes=w_peak_bytes,
                c_slot_bytes=c_slot_bytes,
                num_servers=n,
                parallel=1,
                model_budget_bytes=model_budget_bytes,
            )
        except RuntimeError:
            continue
        p_max = conservative_max_parallel(
            spec,
            num_servers=n,
            tier=tier_for_cap,
            w_all_bytes=w_all_bytes,
            w_peak_bytes=w_peak_bytes,
            c_slot_bytes=c_slot_bytes,
        )
        for p in range(1, p_max + 1):
            try:
                tier = classify_memory_tier(
                    spec,
                    w_all_bytes=w_all_bytes,
                    w_peak_bytes=w_peak_bytes,
                    c_slot_bytes=c_slot_bytes,
                    num_servers=n,
                    parallel=p,
                    model_budget_bytes=model_budget_bytes,
                )
            except RuntimeError:
                continue

            if tier == "warm_stack":
                needed = vram_needed_bytes(
                    n, p, model_bytes=w_all_bytes, c_slot_bytes=c_slot_bytes,
                )
            else:
                needed = vram_needed_bytes(
                    n, p, model_bytes=w_peak_bytes, c_slot_bytes=c_slot_bytes,
                )
            budget = _feasibility_budget_bytes(
                spec, n, tier=tier, model_budget_bytes=model_budget_bytes,
            )
            if budget and needed > budget:
                continue

            max_slots = recommend_max_slots(spec, n, p)
            model_count = len(required_model_names())
            options.append(
                (
                    FleetConfig(
                        num_servers=n,
                        parallel=p,
                        max_slots=max_slots,
                        keep_alive=TIER_KEEP_ALIVE[tier],
                        w_all_bytes=w_all_bytes,
                        w_peak_bytes=w_peak_bytes,
                        c_slot_bytes=c_slot_bytes,
                        memory_tier=tier,
                        model_count=model_count,
                    ),
                    tier,
                )
            )
    return options


def conservative_max_parallel(
    spec: SystemSpec,
    *,
    num_servers: int,
    tier: MemoryTier,
    w_all_bytes: int,
    w_peak_bytes: int,
    c_slot_bytes: int,
) -> int:
    """VRAM/RAM-aware cap on ``OLLAMA_NUM_PARALLEL`` per server."""
    vram_per_server = vram_budget_for_fleet(spec, num_servers) // max(1, num_servers)
    model_bytes = w_all_bytes if tier == "warm_stack" else w_peak_bytes

    if spec.gpu_count <= 1 and num_servers == 1:
        if not vram_per_server:
            return 1
        needed_for_two = model_bytes + 2 * c_slot_bytes
        headroom_after_two = vram_per_server - needed_for_two
        if (
            tier == "warm_stack"
            and needed_for_two <= vram_per_server
            and headroom_after_two >= c_slot_bytes
        ):
            return min(2, MAX_PARALLEL)
        return 1

    if not vram_per_server:
        return 1
    extra = vram_per_server - model_bytes - c_slot_bytes
    if extra < 0:
        return 1
    max_p = 1 + max(0, extra // c_slot_bytes)
    return max(1, min(max_p, MAX_PARALLEL))


def ollama_gates(num_servers: int, parallel: int) -> int:
    """Concurrent Ollama HTTP requests the fleet can safely run."""
    return max(1, num_servers) * max(1, parallel)


def recommend_max_slots(spec: SystemSpec, num_servers: int, parallel: int) -> int:
    gate_slots = ollama_gates(num_servers, parallel)
    ram_slots = max(
        1,
        int((spec.system_ram_bytes * 0.75) // SUBPROCESS_OVERHEAD_BYTES),
    )
    cpu_slots = max(1, spec.cpu_physical)
    return min(gate_slots, ram_slots, cpu_slots)


def _score(spec: SystemSpec, cfg: FleetConfig, tier: MemoryTier) -> float:
    score = float(cfg.agg_lanes)
    if spec.gpu_count == 1:
        if cfg.num_servers == 1:
            score += 3.0
        else:
            score -= 6.0 * cfg.num_servers
        if cfg.parallel == 1:
            score += 2.0
        else:
            score -= 1.5 * (cfg.parallel - 1)
    elif cfg.num_servers > max(1, spec.gpu_count):
        score -= 4.0 * (cfg.num_servers - spec.gpu_count)
    if tier == "warm_stack":
        score += 1.0
    if cfg.max_slots == cfg.agg_lanes:
        score += 1.0
    return score


def recommend(
    spec: SystemSpec,
    *,
    w_all_bytes: int,
    w_peak_bytes: int,
    c_slot_bytes: int,
    model_budget_bytes: int | None = None,
) -> FleetRecommendation:
    feasible = enumerate_feasible(
        spec,
        w_all_bytes=w_all_bytes,
        w_peak_bytes=w_peak_bytes,
        c_slot_bytes=c_slot_bytes,
        model_budget_bytes=model_budget_bytes,
    )
    if not feasible:
        # num_servers=1/parallel=1 has the smallest footprint of any
        # configuration; if it's infeasible, nothing else will be. Let
        # classify_memory_tier raise so budget-specific detail (vs. a
        # generic "this machine" message) reaches the caller.
        classify_memory_tier(
            spec,
            w_all_bytes=w_all_bytes,
            w_peak_bytes=w_peak_bytes,
            c_slot_bytes=c_slot_bytes,
            num_servers=1,
            parallel=1,
            model_budget_bytes=model_budget_bytes,
        )
        raise RuntimeError("No feasible Ollama fleet configuration for this machine")

    best_cfg, best_tier = max(feasible, key=lambda item: _score(spec, item[0], item[1]))
    warnings = tier_warnings(
        best_tier,
        w_all_bytes=w_all_bytes,
        w_peak_bytes=w_peak_bytes,
        spec=spec,
        num_servers=best_cfg.num_servers,
    )
    if best_cfg.max_slots > best_cfg.agg_lanes:
        warnings.append(
            f"{best_cfg.max_slots} job slots exceeds {best_cfg.agg_lanes} Ollama gates; "
            "expect LLM queue waits."
        )

    return FleetRecommendation(
        num_servers=best_cfg.num_servers,
        parallel=best_cfg.parallel,
        max_slots=best_cfg.max_slots,
        keep_alive=best_cfg.keep_alive,
        w_all_bytes=w_all_bytes,
        w_peak_bytes=w_peak_bytes,
        c_slot_bytes=c_slot_bytes,
        memory_tier=best_tier,
        model_count=best_cfg.model_count,
        warnings=tuple(warnings),
    )


def validate_fleet(
    spec: SystemSpec,
    cfg: FleetConfig,
    *,
    model_budget_bytes: int | None = None,
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    w_peak = cfg.w_peak_bytes or cfg.w_all_bytes
    tier = cfg.memory_tier
    if tier == "warm_stack":
        needed = vram_needed_bytes(
            cfg.num_servers,
            cfg.parallel,
            model_bytes=cfg.w_all_bytes,
            c_slot_bytes=cfg.c_slot_bytes,
        )
        budget = _feasibility_budget_bytes(
            spec, cfg.num_servers, tier=tier, model_budget_bytes=model_budget_bytes,
        )
        if budget and needed > budget:
            errors.append(
                f"VRAM exceeded for warm stack: need {needed / 1024**3:.1f} GB, "
                f"budget {budget / 1024**3:.1f} GB"
            )
    else:
        needed = vram_needed_bytes(
            cfg.num_servers,
            cfg.parallel,
            model_bytes=w_peak,
            c_slot_bytes=cfg.c_slot_bytes,
        )
        budget = _feasibility_budget_bytes(
            spec, cfg.num_servers, tier=tier, model_budget_bytes=model_budget_bytes,
        )
        if budget and needed > budget:
            errors.append(
                f"Model memory exceeded: need {needed / 1024**3:.1f} GB, "
                f"VRAM+RAM budget {budget / 1024**3:.1f} GB"
            )
        warnings.extend(
            tier_warnings(
                tier,
                w_all_bytes=cfg.w_all_bytes,
                w_peak_bytes=w_peak,
                spec=spec,
                num_servers=cfg.num_servers,
            )
        )

    if spec.gpu_count == 1 and cfg.num_servers > 1:
        if not any("servers on 1 GPU" in warning for warning in warnings):
            warnings.append("Multiple Ollama servers on one GPU duplicate weights.")
    if cfg.max_slots > cfg.agg_lanes:
        warnings.append(
            f"{cfg.max_slots} slots > {cfg.agg_lanes} Ollama gates; jobs will queue at the router."
        )
    if cfg.num_servers > MAX_SERVERS or cfg.parallel > MAX_PARALLEL:
        errors.append("Requested fleet exceeds policy maximum.")
    if spec.gpu_count > 0 and cfg.num_servers > spec.gpu_count:
        warnings.append(
            f"{cfg.num_servers} servers requested but only {spec.gpu_count} GPU(s) detected; "
            "servers will share GPUs."
        )
    return errors, warnings
