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


def test_parse_model_memory_budget_gb_zero_is_treated_as_unset():
    """"0" has no sensible meaning as a budget; must not silently clamp to 0."""
    assert sizing.parse_model_memory_budget_gb("0") is None
    assert sizing.parse_model_memory_budget_gb("0.0") is None


def test_effective_budget_zero_user_gb_behaves_like_unset():
    spec = _spec_8g_vram_32g_ram()
    cap = sizing.machine_model_cap_bytes(spec, 1)
    parsed = sizing.parse_model_memory_budget_gb("0")
    assert sizing.effective_model_budget_bytes(spec, user_budget_gb=parsed) == cap


def _spec_no_cap() -> SystemSpec:
    return SystemSpec(
        gpu_count=0,
        vram_bytes=(),
        system_ram_bytes=0,
        cpu_physical=1,
        cpu_logical=1,
    )


def test_effective_budget_non_positive_machine_cap_does_not_clamp_user_budget():
    spec = _spec_no_cap()
    assert sizing.machine_model_cap_bytes(spec, 1) <= 0
    user_bytes_expected = 16 * 1024**3
    assert (
        sizing.effective_model_budget_bytes(spec, user_budget_gb=16)
        == user_bytes_expected
    )


def test_effective_budget_non_positive_machine_cap_with_no_user_budget_is_zero():
    spec = _spec_no_cap()
    assert sizing.effective_model_budget_bytes(spec, user_budget_gb=None) == 0


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
