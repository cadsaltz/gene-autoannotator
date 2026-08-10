from worker.fleet import sizing
from worker.probe import SystemSpec


def _spec_8g_vram_32g_ram() -> SystemSpec:
    return SystemSpec(
        gpu_count=1,
        vram_bytes=(8 * 1024**3,),
        system_ram_bytes=32 * 1024**3,
        cpu_physical=6,
        cpu_logical=12,
    )


def test_parse_model_memory_budget_gb():
    assert sizing.parse_model_memory_budget_gb(None) is None
    assert sizing.parse_model_memory_budget_gb("") is None
    assert sizing.parse_model_memory_budget_gb("-1") is None
    assert sizing.parse_model_memory_budget_gb("16") == 16.0


def test_effective_budget_unset_uses_machine_cap():
    spec = _spec_8g_vram_32g_ram()
    cap = sizing.machine_model_cap_bytes(spec, 1)
    assert sizing.effective_model_budget_bytes(spec, user_budget_gb=None) == cap
    assert sizing.effective_model_budget_bytes(spec, user_budget_gb=-1) == cap


def test_effective_budget_clamps_to_machine_cap():
    spec = _spec_8g_vram_32g_ram()
    cap = sizing.machine_model_cap_bytes(spec, 1)
    huge = sizing.effective_model_budget_bytes(spec, user_budget_gb=9999)
    assert huge == cap
    sixteen = sizing.effective_model_budget_bytes(spec, user_budget_gb=16)
    assert sixteen == min(16 * 1024**3, cap)
