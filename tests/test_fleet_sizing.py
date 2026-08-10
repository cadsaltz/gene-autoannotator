from worker.fleet.config import FleetConfig
from worker.fleet import sizing
from worker.probe import SystemSpec


def _laptop_spec():
    return SystemSpec(
        gpu_count=1,
        vram_bytes=(8 * 1024**3,),
        system_ram_bytes=31 * 1024**3,
        cpu_physical=6,
        cpu_logical=12,
    )


def _rtx2070_performance_spec():
    return SystemSpec(
        gpu_count=1,
        vram_bytes=(8 * 1024**3,),
        system_ram_bytes=32 * 1024**3,
        cpu_physical=6,
        cpu_logical=12,
    )


def test_feasible_pairs_exclude_vram_overflow_for_warm_stack():
    spec = _laptop_spec()
    w_all = int(2.0 * 1024**3)
    w_peak = int(1.2 * 1024**3)
    c_slot = int(0.4 * 1024**3)
    feasible = sizing.enumerate_feasible(
        spec, w_all_bytes=w_all, w_peak_bytes=w_peak, c_slot_bytes=c_slot,
    )
    hosts = {(item[0].num_servers, item[0].parallel) for item in feasible}
    assert (3, 2) not in hosts
    assert (1, 2) in hosts


def test_recommend_max_slots_never_exceeds_ollama_gates():
    spec = _laptop_spec()
    assert sizing.recommend_max_slots(spec, 1, 1) == 1
    assert sizing.recommend_max_slots(spec, 2, 2) == 4


def test_conservative_max_parallel_single_gpu_defaults_to_one():
    spec = _laptop_spec()
    cap = sizing.conservative_max_parallel(
        spec,
        num_servers=1,
        tier="warm_stack",
        w_all_bytes=int(6 * 1024**3),
        w_peak_bytes=int(1.2 * 1024**3),
        c_slot_bytes=int(0.4 * 1024**3),
    )
    assert cap == 1


def test_laptop_recommendation_is_conservative():
    spec = _laptop_spec()
    w_all = int(2.0 * 1024**3)
    w_peak = int(1.2 * 1024**3)
    c_slot = int(0.4 * 1024**3)
    rec = sizing.recommend(
        spec, w_all_bytes=w_all, w_peak_bytes=w_peak, c_slot_bytes=c_slot,
    )
    assert rec.num_servers == 1
    assert rec.parallel == 1
    assert rec.max_slots == rec.agg_lanes


def test_recommendation_favors_single_server_on_one_gpu():
    spec = _laptop_spec()
    w_all = int(2.0 * 1024**3)
    w_peak = int(1.2 * 1024**3)
    c_slot = int(0.4 * 1024**3)
    rec = sizing.recommend(
        spec, w_all_bytes=w_all, w_peak_bytes=w_peak, c_slot_bytes=c_slot,
    )
    assert rec.num_servers == 1
    assert rec.parallel >= 1
    assert rec.agg_lanes == rec.num_servers * rec.parallel


def test_performance_models_fit_with_swap_tier_on_8gb_gpu():
    spec = _rtx2070_performance_spec()
    w_all = int(52 * 1024**3)
    w_peak = int(16 * 1024**3)
    c_slot = int(0.4 * 1024**3)
    rec = sizing.recommend(
        spec, w_all_bytes=w_all, w_peak_bytes=w_peak, c_slot_bytes=c_slot,
    )
    assert rec.num_servers == 1
    assert rec.memory_tier in ("swap", "vram_overflow")
    assert rec.keep_alive == "0"
    assert rec.warnings


def test_classify_warm_stack_when_all_models_fit_vram():
    spec = _laptop_spec()
    tier = sizing.classify_memory_tier(
        spec,
        w_all_bytes=int(2 * 1024**3),
        w_peak_bytes=int(1.2 * 1024**3),
        c_slot_bytes=int(0.4 * 1024**3),
    )
    assert tier == "warm_stack"


def test_classify_vram_overflow_when_peak_exceeds_vram():
    spec = _rtx2070_performance_spec()
    tier = sizing.classify_memory_tier(
        spec,
        w_all_bytes=int(52 * 1024**3),
        w_peak_bytes=int(16 * 1024**3),
        c_slot_bytes=int(0.4 * 1024**3),
    )
    assert tier == "vram_overflow"


def test_validate_blocks_warm_stack_vram_error():
    spec = _laptop_spec()
    errors, warnings = sizing.validate_fleet(
        spec,
        FleetConfig(
            num_servers=10,
            parallel=4,
            max_slots=40,
            w_all_bytes=2 * 1024**3,
            w_peak_bytes=1 * 1024**3,
            c_slot_bytes=int(0.4 * 1024**3),
            memory_tier="warm_stack",
        ),
    )
    assert errors


def test_validate_allows_swap_tier_with_large_w_all():
    spec = _rtx2070_performance_spec()
    errors, _warnings = sizing.validate_fleet(
        spec,
        FleetConfig(
            num_servers=1,
            parallel=2,
            max_slots=2,
            w_all_bytes=int(52 * 1024**3),
            w_peak_bytes=int(16 * 1024**3),
            c_slot_bytes=int(0.4 * 1024**3),
            memory_tier="vram_overflow",
            keep_alive="0",
        ),
    )
    assert not errors


def _big_vram_spec():
    """1 GPU with enough VRAM that peak (but not warm) fits -- classic swap case."""
    return SystemSpec(
        gpu_count=1,
        vram_bytes=(24 * 1024**3,),
        system_ram_bytes=32 * 1024**3,
        cpu_physical=8,
        cpu_logical=16,
    )


def test_classify_swap_tier_without_budget_still_works():
    spec = _big_vram_spec()
    tier = sizing.classify_memory_tier(
        spec,
        w_all_bytes=int(100 * 1024**3),  # warm-stack never fits
        w_peak_bytes=int(10 * 1024**3),  # peak fits comfortably in VRAM
        c_slot_bytes=int(0.4 * 1024**3),
    )
    assert tier == "swap"


def test_classify_memory_tier_swap_path_rejects_when_budget_below_peak_need():
    """Critical fix: swap tier must not ignore model_budget_bytes.

    Peak need fits in VRAM (would classify as "swap" pre-fix), but the
    user's model_budget_bytes is smaller than peak need, so swap must be
    rejected -- and since the clamped total budget is also below peak
    need, no tier is feasible and a clear error should be raised.
    """
    spec = _big_vram_spec()
    w_all = int(100 * 1024**3)
    w_peak = int(10 * 1024**3)
    c_slot = int(0.4 * 1024**3)
    peak_need = sizing.vram_needed_bytes(
        1, 1, model_bytes=w_peak, c_slot_bytes=c_slot,
    )
    tight_budget = int(5 * 1024**3)
    assert tight_budget < peak_need  # sanity: budget is genuinely tighter than need

    try:
        sizing.classify_memory_tier(
            spec,
            w_all_bytes=w_all,
            w_peak_bytes=w_peak,
            c_slot_bytes=c_slot,
            model_budget_bytes=tight_budget,
        )
    except RuntimeError as exc:
        message = str(exc)
        assert "WORKER_MODEL_MEMORY_BUDGET_GB" in message
        assert "budget" in message.lower()
    else:
        raise AssertionError("expected RuntimeError when budget < peak need")


def test_classify_memory_tier_swap_path_accepts_when_budget_covers_peak_need():
    spec = _big_vram_spec()
    w_all = int(100 * 1024**3)
    w_peak = int(10 * 1024**3)
    c_slot = int(0.4 * 1024**3)
    peak_need = sizing.vram_needed_bytes(1, 1, model_bytes=w_peak, c_slot_bytes=c_slot)
    generous_budget = peak_need + int(1 * 1024**3)

    tier = sizing.classify_memory_tier(
        spec,
        w_all_bytes=w_all,
        w_peak_bytes=w_peak,
        c_slot_bytes=c_slot,
        model_budget_bytes=generous_budget,
    )
    assert tier == "swap"


def test_recommend_raises_budget_specific_error_when_tight_budget_infeasible():
    """With model_budget_bytes far below peak footprint, recommend() must
    either find a feasible config under budget or raise a clear
    budget-related error -- not silently pick a wrong tier."""
    spec = _laptop_spec()
    w_all = int(20 * 1024**3)
    w_peak = int(10 * 1024**3)
    c_slot = int(0.4 * 1024**3)
    tiny_budget = int(1 * 1024**3)  # far below even the smallest footprint

    try:
        rec = sizing.recommend(
            spec,
            w_all_bytes=w_all,
            w_peak_bytes=w_peak,
            c_slot_bytes=c_slot,
            model_budget_bytes=tiny_budget,
        )
    except RuntimeError as exc:
        message = str(exc)
        assert "WORKER_MODEL_MEMORY_BUDGET_GB" in message
        assert "budget" in message.lower()
    else:
        # If somehow feasible, the winning config really must respect budget.
        needed = sizing.vram_needed_bytes(
            rec.num_servers,
            rec.parallel,
            model_bytes=w_peak if rec.memory_tier != "warm_stack" else w_all,
            c_slot_bytes=c_slot,
        )
        assert needed <= tiny_budget


def test_recommend_finds_feasible_config_when_budget_allows_smaller_footprint():
    spec = _laptop_spec()
    w_all = int(2.0 * 1024**3)
    w_peak = int(1.2 * 1024**3)
    c_slot = int(0.4 * 1024**3)
    generous_budget = int(4 * 1024**3)

    rec = sizing.recommend(
        spec,
        w_all_bytes=w_all,
        w_peak_bytes=w_peak,
        c_slot_bytes=c_slot,
        model_budget_bytes=generous_budget,
    )
    needed = sizing.vram_needed_bytes(
        rec.num_servers,
        rec.parallel,
        model_bytes=w_all if rec.memory_tier == "warm_stack" else w_peak,
        c_slot_bytes=c_slot,
    )
    assert needed <= generous_budget
