from worker.router.residency import (
    DEFAULT_PACK_FACTOR,
    DEFAULT_RUNTIME_INFLATE,
    GiB,
    effective_residency_sizes,
    pack_budget_bytes,
    pack_models_largest_first,
    select_residency_mode,
)

LAPTOP_SIZES = {
    "gemma3:27b": int(17.0 * GiB),
    "qwen3:14b": int(9.3 * GiB),
    "gemma3:12b": int(8.1 * GiB),
    "mistral-nemo:12b": int(7.1 * GiB),
    "qwen3:8b": int(5.2 * GiB),
}
LAPTOP_CACHE_BUDGET = int(35.3 * GiB)


def test_pack_stops_at_first_that_does_not_fit():
    # Largest 30 fits; next 25 does not — do not skip to 10.
    sizes = {"a": 10, "b": 30, "c": 25}
    assert pack_models_largest_first(sizes, 40) == ["b"]


def test_only_largest_fits_is_single():
    sizes = {"big": 100, "small": 80}
    plan = select_residency_mode(sizes, cache_budget_bytes=100, pack_factor=1.0)
    assert plan.mode == "single"
    assert plan.packed_models == ["big"]
    assert plan.max_loaded == 1
    assert not plan.use_model_cache
    assert not plan.should_prewarm


def test_partial_pack_is_cache():
    sizes = {"a": 50, "b": 40, "c": 30}
    plan = select_residency_mode(sizes, cache_budget_bytes=90, pack_factor=1.0)
    assert plan.mode == "cache"
    assert plan.packed_models == ["a", "b"]
    assert plan.max_loaded == 2
    assert plan.use_model_cache
    assert not plan.should_prewarm


def test_full_pack_is_warm_stack():
    sizes = {"a": 10, "b": 20, "c": 30}
    plan = select_residency_mode(sizes, cache_budget_bytes=60, pack_factor=1.0)
    assert plan.mode == "warm_stack"
    assert set(plan.packed_models) == set(sizes)
    assert plan.max_loaded == 3
    assert plan.should_prewarm
    assert not plan.use_model_cache


def test_zero_budget_is_single_empty_pack():
    plan = select_residency_mode({"a": 10}, cache_budget_bytes=0, pack_factor=1.0)
    assert plan.mode == "single"
    assert plan.packed_models == []
    assert plan.max_loaded == 1


def test_pack_budget_applies_factor():
    assert pack_budget_bytes(1000, factor=0.70) == 700
    assert DEFAULT_PACK_FACTOR == 0.70


def test_laptop_fixture_factor_070_is_single():
    plan = select_residency_mode(
        LAPTOP_SIZES,
        cache_budget_bytes=LAPTOP_CACHE_BUDGET,
        pack_factor=0.70,
    )
    assert plan.mode == "single"
    assert plan.packed_models == ["gemma3:27b"]
    assert plan.max_loaded == 1


def test_laptop_fixture_factor_100_is_cache_three():
    plan = select_residency_mode(
        LAPTOP_SIZES,
        cache_budget_bytes=LAPTOP_CACHE_BUDGET,
        pack_factor=1.0,
    )
    assert plan.mode == "cache"
    assert plan.packed_models == ["gemma3:27b", "qwen3:14b", "gemma3:12b"]
    assert plan.max_loaded == 3


def test_effective_residency_sizes_inflate_and_c_slot():
    weights = {"qwen3:14b": int(9.3 * GiB)}
    # 9.3 * 1.4 + 2 * 0.4 ≈ 13.82 GiB — close to observed ollama ps ~14 GiB.
    effective = effective_residency_sizes(
        weights,
        inflate=1.40,
        parallel=2,
        c_slot_bytes=int(0.4 * GiB),
    )
    assert abs(effective["qwen3:14b"] / GiB - 13.82) < 0.05
    assert DEFAULT_RUNTIME_INFLATE == 1.40


def test_laptop_inflated_sizes_still_single_at_070():
    inflated = effective_residency_sizes(
        LAPTOP_SIZES, inflate=1.40, parallel=2, c_slot_bytes=int(0.4 * GiB)
    )
    plan = select_residency_mode(
        inflated,
        cache_budget_bytes=LAPTOP_CACHE_BUDGET,
        pack_factor=0.70,
    )
    assert plan.mode == "single"
    assert plan.packed_models == ["gemma3:27b"]
