from worker.fleet import sizing
from worker.probe import SystemSpec


def _spec(*, vram_gb=8.0, ram_gb=32.0) -> SystemSpec:
    return SystemSpec(
        gpu_count=1,
        vram_bytes=(int(vram_gb * 1024**3),),
        system_ram_bytes=int(ram_gb * 1024**3),
        cpu_physical=8,
        cpu_logical=16,
    )


def test_cache_budget_applies_10_percent_headroom_on_vram_and_ram():
    spec = _spec(vram_gb=10.0, ram_gb=20.0)
    # 0.9*10 + 0.9*20 = 27 GB
    expected = int(0.9 * 10 * 1024**3) + int(0.9 * 20 * 1024**3)
    assert sizing.cache_budget_bytes(spec) == expected


def test_cache_budget_respects_user_cap_gb():
    spec = _spec(vram_gb=10.0, ram_gb=20.0)
    capped = sizing.cache_budget_bytes(spec, user_budget_gb=12.0)
    assert capped == int(12.0 * 1024**3)


def test_cache_budget_ignores_unset_user_cap():
    spec = _spec(vram_gb=10.0, ram_gb=20.0)
    assert sizing.cache_budget_bytes(spec, user_budget_gb=None) == sizing.cache_budget_bytes(spec)
    assert sizing.cache_budget_bytes(spec, user_budget_gb=-1) == sizing.cache_budget_bytes(spec)
