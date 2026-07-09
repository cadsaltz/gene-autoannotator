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


def test_feasible_pairs_exclude_vram_overflow():
    spec = _laptop_spec()
    w_all = int(2.0 * 1024**3)
    c_slot = int(0.4 * 1024**3)
    feasible = sizing.enumerate_feasible(spec, w_all_bytes=w_all, c_slot_bytes=c_slot)
    hosts = {(item.num_servers, item.parallel) for item in feasible}
    assert (3, 2) not in hosts
    assert (2, 1) in hosts


def test_recommendation_favors_single_gpu_higher_p():
    spec = _laptop_spec()
    w_all = int(2.0 * 1024**3)
    c_slot = int(0.4 * 1024**3)
    rec = sizing.recommend(spec, w_all_bytes=w_all, c_slot_bytes=c_slot)
    assert rec.num_servers >= 1
    assert rec.parallel >= 1
    assert rec.agg_lanes == rec.num_servers * rec.parallel


def test_validate_blocks_vram_error():
    spec = _laptop_spec()
    errors, warnings = sizing.validate_fleet(
        spec,
        FleetConfig(num_servers=10, parallel=4, max_slots=40, w_all_bytes=2 * 1024**3, c_slot_bytes=int(0.4 * 1024**3)),
    )
    assert errors
