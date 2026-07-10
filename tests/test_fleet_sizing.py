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


def test_recommendation_favors_single_gpu_higher_parallel():
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
    assert any("keep_alive=0" in warning for warning in rec.warnings)


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
