from worker.fleet.config import FleetConfig
from worker.fleet.sizing import FleetRecommendation
from worker.fleet import sizing
from worker.fleet.supervisor import FleetSupervisor
from worker.fleet import setup
from worker.probe import SystemSpec


def test_prompt_int_defaults_on_empty(monkeypatch):
    monkeypatch.setattr(setup, "_read_line", lambda prompt: "")
    assert setup._prompt_int("servers", recommended=2) == 2


def test_validate_or_warn_returns_errors():
    spec = SystemSpec(
        gpu_count=1,
        vram_bytes=(8 * 1024**3,),
        system_ram_bytes=31 * 1024**3,
        cpu_physical=6,
        cpu_logical=12,
    )
    cfg = FleetConfig(
        num_servers=99,
        parallel=50,
        max_slots=99,
        w_all_bytes=2 * 1024**3,
        c_slot_bytes=int(0.4 * 1024**3),
    )
    errors, warnings = setup.validate_or_warn(spec, cfg)
    assert errors


def test_prompt_fleet_accepts_valid_config(monkeypatch):
    spec = SystemSpec(
        gpu_count=1,
        vram_bytes=(8 * 1024**3,),
        system_ram_bytes=31 * 1024**3,
        cpu_physical=6,
        cpu_logical=12,
    )
    recommendation = FleetRecommendation(
        num_servers=2,
        parallel=1,
        max_slots=2,
        w_all_bytes=2 * 1024**3,
        c_slot_bytes=int(0.4 * 1024**3),
    )
    responses = iter(["", "", ""])
    monkeypatch.setattr(setup, "_read_line", lambda prompt: next(responses))
    cfg = setup.prompt_fleet(spec, recommendation)
    assert cfg.num_servers == 2
    assert cfg.parallel == 1
    assert cfg.max_slots == 2


def test_normalize_fleet_config_preserves_slots_when_budget_is_infeasible(monkeypatch):
    spec = SystemSpec(
        gpu_count=1,
        vram_bytes=(8 * 1024**3,),
        system_ram_bytes=31 * 1024**3,
        cpu_physical=6,
        cpu_logical=12,
    )
    cfg = FleetConfig(num_servers=2, parallel=3, max_slots=7, keep_alive="5m")
    recommendation = FleetRecommendation(
        num_servers=1,
        parallel=1,
        max_slots=1,
        keep_alive="0",
        w_all_bytes=2 * 1024**3,
        w_peak_bytes=1 * 1024**3,
        c_slot_bytes=int(0.4 * 1024**3),
        memory_tier="swap",
    )

    def raise_infeasible(*_args, **_kwargs):
        raise RuntimeError("model budget is infeasible")

    monkeypatch.setattr(setup.sizing, "classify_memory_tier", raise_infeasible)
    monkeypatch.setattr(setup.sizing, "recommend", lambda *_args, **_kwargs: recommendation)

    normalized = setup._normalize_fleet_config(
        cfg,
        spec,
        model_budget_bytes=2 * 1024**3,
    )

    assert normalized.max_slots == 7
    assert normalized.num_servers == 1
    assert normalized.parallel == 1


def test_start_fleet_launches_one_process_per_server(monkeypatch):
    spec = SystemSpec(
        gpu_count=2,
        vram_bytes=(8 * 1024**3, 8 * 1024**3),
        system_ram_bytes=31 * 1024**3,
        cpu_physical=6,
        cpu_logical=12,
    )
    cfg = FleetConfig(
        num_servers=2,
        parallel=3,
        max_slots=4,
        w_all_bytes=2 * 1024**3,
        c_slot_bytes=int(0.4 * 1024**3),
    )
    launched: list[tuple[int, int, int | None]] = []

    class FakePopen:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

    def fake_start(*, port, parallel, gpu_index, max_loaded_models=None):
        launched.append((port, parallel, gpu_index))
        return FakePopen()

    monkeypatch.setattr(setup, "start_ollama_server", fake_start)
    monkeypatch.setattr(setup, "_ensure_ports_free", lambda ports, **kw: None)
    procs = setup.start_fleet(cfg, spec)
    assert len(procs) == 2
    assert launched == [(11434, 3, 0), (11435, 3, 1)]


def test_build_ollama_server_env_does_not_inherit_parent_host(monkeypatch):
    monkeypatch.setenv("OLLAMA_HOST", "http://127.0.0.1:11434")
    monkeypatch.delenv("OLLAMA_CONTEXT_LENGTH", raising=False)
    monkeypatch.delenv("OLLAMA_FLEET_SLOT_CTX", raising=False)
    env = setup._build_ollama_server_env(port=11435, parallel=2, gpu_index=0)
    assert env["OLLAMA_HOST"] == "127.0.0.1:11435"
    assert env["OLLAMA_NUM_PARALLEL"] == "2"
    assert env["OLLAMA_CONTEXT_LENGTH"] == "16384"  # 2 slots × 8192
    assert env["CUDA_VISIBLE_DEVICES"] == "0"


def test_effective_ollama_context_length_scales_with_parallel(monkeypatch):
    monkeypatch.delenv("OLLAMA_CONTEXT_LENGTH", raising=False)
    monkeypatch.delenv("OLLAMA_FLEET_SLOT_CTX", raising=False)
    assert setup.effective_ollama_context_length(parallel=2) == 16384
    assert setup.effective_ollama_context_length(parallel=1) == 8192


def test_effective_ollama_context_length_respects_explicit_total(monkeypatch):
    monkeypatch.setenv("OLLAMA_CONTEXT_LENGTH", "32768")
    assert setup.effective_ollama_context_length(parallel=2) == 32768


def test_effective_ollama_context_length_respects_slot_override(monkeypatch):
    monkeypatch.delenv("OLLAMA_CONTEXT_LENGTH", raising=False)
    monkeypatch.setenv("OLLAMA_FLEET_SLOT_CTX", "12288")
    assert setup.effective_ollama_context_length(parallel=2) == 24576


def test_effective_max_loaded_models_defaults_to_one_for_swap_tier(monkeypatch):
    monkeypatch.delenv("OLLAMA_MAX_LOADED_MODELS", raising=False)
    cfg = FleetConfig(
        num_servers=1,
        parallel=1,
        max_slots=1,
        memory_tier="swap",
        model_count=4,
    )
    assert setup.effective_max_loaded_models(cfg) == 1


def test_effective_max_loaded_models_uses_model_count_for_warm_stack(monkeypatch):
    monkeypatch.delenv("OLLAMA_MAX_LOADED_MODELS", raising=False)
    cfg = FleetConfig(
        num_servers=1,
        parallel=1,
        max_slots=1,
        memory_tier="warm_stack",
        model_count=4,
    )
    assert setup.effective_max_loaded_models(cfg) == 4


def test_effective_max_loaded_models_respects_env_override(monkeypatch):
    monkeypatch.setenv("OLLAMA_MAX_LOADED_MODELS", "2")
    cfg = FleetConfig(num_servers=1, parallel=1, max_slots=1, memory_tier="swap")
    assert setup.effective_max_loaded_models(cfg) == 2


def test_normalize_preserves_explicit_keep_alive(monkeypatch):
    from worker.fleet import setup
    from worker.fleet.config import FleetConfig
    from worker.probe import SystemSpec

    spec = SystemSpec(
        gpu_count=1,
        vram_bytes=(8 * 1024**3,),
        system_ram_bytes=32 * 1024**3,
        cpu_physical=6,
        cpu_logical=12,
    )
    cfg = FleetConfig(
        num_servers=1,
        parallel=2,
        max_slots=2,
        keep_alive="5m",
        w_all_bytes=20 * 1024**3,
        w_peak_bytes=12 * 1024**3,
        c_slot_bytes=int(0.4 * 1024**3),
        memory_tier="vram_overflow",
    )
    out = setup._normalize_fleet_config(cfg, spec, preserve_keep_alive=True)
    assert out.keep_alive == "5m"

    out2 = setup._normalize_fleet_config(cfg, spec, preserve_keep_alive=False)
    assert out2.keep_alive == "0"  # tier map for vram_overflow


def test_normalize_infeasible_fallback_preserves_explicit_keep_alive(monkeypatch):
    spec = SystemSpec(
        gpu_count=1,
        vram_bytes=(8 * 1024**3,),
        system_ram_bytes=32 * 1024**3,
        cpu_physical=6,
        cpu_logical=12,
    )
    cfg = FleetConfig(
        num_servers=99,
        parallel=99,
        max_slots=99,
        keep_alive="5m",
        w_all_bytes=20 * 1024**3,
        w_peak_bytes=12 * 1024**3,
        c_slot_bytes=int(0.4 * 1024**3),
    )
    rec = FleetRecommendation(
        num_servers=1,
        parallel=1,
        max_slots=1,
        keep_alive="0",
        w_all_bytes=20 * 1024**3,
        w_peak_bytes=12 * 1024**3,
        c_slot_bytes=int(0.4 * 1024**3),
        memory_tier="swap",
    )

    def boom(*args, **kwargs):
        raise RuntimeError("infeasible")

    monkeypatch.setattr(setup.sizing, "classify_memory_tier", boom)
    monkeypatch.setattr(setup.sizing, "recommend", lambda *args, **kwargs: rec)

    out = setup._normalize_fleet_config(cfg, spec, preserve_keep_alive=True)
    assert out.keep_alive == "5m"

    out2 = setup._normalize_fleet_config(cfg, spec, preserve_keep_alive=False)
    assert out2.keep_alive == "0"


def test_refresh_fleet_footprints_preserves_explicit_keep_alive(tmp_path, monkeypatch):
    env_path = tmp_path / "worker.env"
    env_path.write_text("OLLAMA_FLEET_KEEP_ALIVE=5m\n", encoding="utf-8")
    spec = SystemSpec(
        gpu_count=1,
        vram_bytes=(8 * 1024**3,),
        system_ram_bytes=32 * 1024**3,
        cpu_physical=6,
        cpu_logical=12,
    )
    cfg = FleetConfig(
        num_servers=1,
        parallel=2,
        max_slots=2,
        keep_alive="5m",
        w_all_bytes=20 * 1024**3,
        w_peak_bytes=12 * 1024**3,
        c_slot_bytes=int(0.4 * 1024**3),
        memory_tier="vram_overflow",
    )
    monkeypatch.setattr(
        setup.models,
        "resolve_footprints",
        lambda **kw: (22 * 1024**3, 12 * 1024**3, "manifest"),
    )
    persisted: list[FleetConfig] = []
    monkeypatch.setattr(setup, "_persist_fleet_config", lambda path, c: persisted.append(c))
    monkeypatch.setattr(setup, "_apply_fleet_to_environ", lambda c: None)

    out = setup.refresh_fleet_footprints(cfg, spec, host="127.0.0.1:11434", env_path=env_path)
    assert out.keep_alive == "5m"
    assert persisted[-1].keep_alive == "5m"


def test_refresh_fleet_footprints_forwards_model_budget_bytes(tmp_path, monkeypatch):
    env_path = tmp_path / "worker.env"
    env_path.write_text("", encoding="utf-8")
    spec = SystemSpec(
        gpu_count=1,
        vram_bytes=(8 * 1024**3,),
        system_ram_bytes=32 * 1024**3,
        cpu_physical=6,
        cpu_logical=12,
    )
    cfg = FleetConfig(
        num_servers=1,
        parallel=2,
        max_slots=2,
        keep_alive="0",
        w_all_bytes=20 * 1024**3,
        w_peak_bytes=12 * 1024**3,
        c_slot_bytes=int(0.4 * 1024**3),
        memory_tier="vram_overflow",
    )
    monkeypatch.setenv("WORKER_MODEL_MEMORY_BUDGET_GB", "16")
    monkeypatch.setattr(
        setup.models,
        "resolve_footprints",
        lambda **kw: (22 * 1024**3, 12 * 1024**3, "manifest"),
    )
    captured: dict[str, int | None] = {}

    def fake_normalize(cfg, spec, *, preserve_keep_alive=False, model_budget_bytes=None):
        captured["model_budget_bytes"] = model_budget_bytes
        return cfg

    monkeypatch.setattr(setup, "_normalize_fleet_config", fake_normalize)
    monkeypatch.setattr(setup, "_persist_fleet_config", lambda path, c: None)
    monkeypatch.setattr(setup, "_apply_fleet_to_environ", lambda c: None)

    setup.refresh_fleet_footprints(cfg, spec, host="127.0.0.1:11434", env_path=env_path)

    expected = sizing.effective_model_budget_bytes(spec, user_budget_gb=16.0)
    assert captured["model_budget_bytes"] == expected


_FLEET_ENV_KEYS_TO_ISOLATE = (
    "OLLAMA_FLEET_SERVERS",
    "OLLAMA_FLEET_PARALLEL",
    "WORKER_MAX_SLOTS",
    "OLLAMA_FLEET_W_ALL_BYTES",
    "OLLAMA_FLEET_W_PEAK_BYTES",
    "OLLAMA_FLEET_C_SLOT_BYTES",
    "OLLAMA_FLEET_MEMORY_TIER",
    "OLLAMA_FLEET_KEEP_ALIVE",
    "AUTOANNOTATION_OLLAMA_KEEP_ALIVE",
    "WORKER_MODEL_MEMORY_BUDGET_GB",
    "ANNOTATION_MEMORY_BUDGET_GB",
)


def _isolate_fleet_env(monkeypatch):
    """Clear real process env fleet keys so a test's assertions aren't
    contaminated by ``_apply_fleet_to_environ`` mutations from earlier tests
    (or by this test's own real-env side effects leaking to later tests).
    """
    for key in _FLEET_ENV_KEYS_TO_ISOLATE:
        monkeypatch.delenv(key, raising=False)


def test_refresh_fleet_footprints_reads_budget_via_env_value_from_file(tmp_path, monkeypatch):
    """Important fix: budget lookup must use _env_value (file+env), not bare os.getenv."""
    _isolate_fleet_env(monkeypatch)
    env_path = tmp_path / "worker.env"
    env_path.write_text("WORKER_MODEL_MEMORY_BUDGET_GB=16\n", encoding="utf-8")
    spec = SystemSpec(
        gpu_count=1,
        vram_bytes=(8 * 1024**3,),
        system_ram_bytes=32 * 1024**3,
        cpu_physical=6,
        cpu_logical=12,
    )
    cfg = FleetConfig(
        num_servers=1,
        parallel=2,
        max_slots=2,
        keep_alive="0",
        w_all_bytes=20 * 1024**3,
        w_peak_bytes=12 * 1024**3,
        c_slot_bytes=int(0.4 * 1024**3),
        memory_tier="vram_overflow",
    )
    monkeypatch.setattr(
        setup.models,
        "resolve_footprints",
        lambda **kw: (22 * 1024**3, 12 * 1024**3, "manifest"),
    )
    captured: dict[str, int | None] = {}

    def fake_normalize(cfg, spec, *, preserve_keep_alive=False, model_budget_bytes=None):
        captured["model_budget_bytes"] = model_budget_bytes
        return cfg

    monkeypatch.setattr(setup, "_normalize_fleet_config", fake_normalize)
    monkeypatch.setattr(setup, "_persist_fleet_config", lambda path, c: None)
    monkeypatch.setattr(setup, "_apply_fleet_to_environ", lambda c: None)

    setup.refresh_fleet_footprints(cfg, spec, host="127.0.0.1:11434", env_path=env_path)

    expected = sizing.effective_model_budget_bytes(spec, user_budget_gb=16.0)
    assert captured["model_budget_bytes"] == expected


def test_ensure_fleet_config_reads_legacy_budget_alias_from_env_file(tmp_path, monkeypatch):
    """Legacy ANNOTATION_MEMORY_BUDGET_GB in the file must resolve via _env_value too."""
    _isolate_fleet_env(monkeypatch)
    monkeypatch.setattr(setup, "_apply_fleet_to_environ", lambda c: None)
    env_path = tmp_path / "worker.env"
    env_path.write_text(
        "\n".join(
            [
                "OLLAMA_FLEET_SERVERS=1",
                "OLLAMA_FLEET_PARALLEL=1",
                "WORKER_MAX_SLOTS=1",
                "ANNOTATION_MEMORY_BUDGET_GB=16",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    spec = SystemSpec(
        gpu_count=1,
        vram_bytes=(8 * 1024**3,),
        system_ram_bytes=31 * 1024**3,
        cpu_physical=6,
        cpu_logical=12,
    )
    captured: dict[str, int | None] = {}
    real_normalize = setup._normalize_fleet_config

    def spy_normalize(cfg, spec, *, preserve_keep_alive=False, model_budget_bytes=None):
        captured["model_budget_bytes"] = model_budget_bytes
        return real_normalize(
            cfg,
            spec,
            preserve_keep_alive=preserve_keep_alive,
            model_budget_bytes=model_budget_bytes,
        )

    monkeypatch.setattr(setup, "_normalize_fleet_config", spy_normalize)
    setup.ensure_fleet_config(interactive=False, env_path=env_path, spec=spec)

    expected = sizing.effective_model_budget_bytes(spec, user_budget_gb=16.0)
    assert captured["model_budget_bytes"] == expected


def test_refresh_fleet_footprints_does_not_preserve_process_only_keep_alive(tmp_path, monkeypatch):
    """Important fix: keep-alive preserve must check the env *file*, not os.environ.

    Simulates a prior ensure_fleet_config call that auto-applied a tier-derived
    keep_alive into os.environ (via _apply_fleet_to_environ) without the user
    ever setting it explicitly in worker.env. A later refresh must not mistake
    that process-env value for explicit user intent.
    """
    _isolate_fleet_env(monkeypatch)
    env_path = tmp_path / "worker.env"
    env_path.write_text("", encoding="utf-8")  # no explicit keep-alive in the file
    monkeypatch.setenv("OLLAMA_FLEET_KEEP_ALIVE", "5m")  # auto-applied, not user-set
    spec = SystemSpec(
        gpu_count=1,
        vram_bytes=(8 * 1024**3,),
        system_ram_bytes=32 * 1024**3,
        cpu_physical=6,
        cpu_logical=12,
    )
    cfg = FleetConfig(
        num_servers=1,
        parallel=2,
        max_slots=2,
        keep_alive="5m",
        w_all_bytes=20 * 1024**3,
        w_peak_bytes=12 * 1024**3,
        c_slot_bytes=int(0.4 * 1024**3),
        memory_tier="vram_overflow",
    )
    monkeypatch.setattr(
        setup.models,
        "resolve_footprints",
        lambda **kw: (22 * 1024**3, 12 * 1024**3, "manifest"),
    )
    monkeypatch.setattr(setup, "_persist_fleet_config", lambda path, c: None)
    monkeypatch.setattr(setup, "_apply_fleet_to_environ", lambda c: None)

    out = setup.refresh_fleet_footprints(cfg, spec, host="127.0.0.1:11434", env_path=env_path)

    # vram_overflow tier's mapped keep_alive is "0"; process-env "5m" must not win.
    assert out.keep_alive == "0"


def test_ensure_fleet_config_does_not_preserve_process_only_keep_alive(tmp_path, monkeypatch):
    _isolate_fleet_env(monkeypatch)
    monkeypatch.setattr(setup, "_apply_fleet_to_environ", lambda c: None)
    env_path = tmp_path / "worker.env"
    env_path.write_text(
        "\n".join(
            [
                "OLLAMA_FLEET_SERVERS=1",
                "OLLAMA_FLEET_PARALLEL=2",
                "WORKER_MAX_SLOTS=2",
                "OLLAMA_FLEET_W_ALL_BYTES=21474836480",
                "OLLAMA_FLEET_W_PEAK_BYTES=12884901888",
                "OLLAMA_FLEET_MEMORY_TIER=vram_overflow",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("OLLAMA_FLEET_KEEP_ALIVE", "5m")  # auto-applied, not user-set in file
    spec = SystemSpec(
        gpu_count=1,
        vram_bytes=(8 * 1024**3,),
        system_ram_bytes=32 * 1024**3,
        cpu_physical=6,
        cpu_logical=12,
    )
    cfg = setup.ensure_fleet_config(interactive=False, env_path=env_path, spec=spec)
    assert cfg.keep_alive == "0"


def test_ensure_fleet_config_preserves_keep_alive_explicit_in_file(tmp_path, monkeypatch):
    _isolate_fleet_env(monkeypatch)
    monkeypatch.setattr(setup, "_apply_fleet_to_environ", lambda c: None)
    env_path = tmp_path / "worker.env"
    env_path.write_text(
        "\n".join(
            [
                "OLLAMA_FLEET_SERVERS=1",
                "OLLAMA_FLEET_PARALLEL=2",
                "WORKER_MAX_SLOTS=2",
                "OLLAMA_FLEET_W_ALL_BYTES=21474836480",
                "OLLAMA_FLEET_W_PEAK_BYTES=12884901888",
                "OLLAMA_FLEET_MEMORY_TIER=vram_overflow",
                "OLLAMA_FLEET_KEEP_ALIVE=5m",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    spec = SystemSpec(
        gpu_count=1,
        vram_bytes=(8 * 1024**3,),
        system_ram_bytes=32 * 1024**3,
        cpu_physical=6,
        cpu_logical=12,
    )
    cfg = setup.ensure_fleet_config(interactive=False, env_path=env_path, spec=spec)
    assert cfg.keep_alive == "5m"


def test_ensure_fleet_config_saved_path_infeasible_under_tight_budget_raises_budget_error(
    tmp_path, monkeypatch,
):
    """Critical fix #2: saved fleet path under a tight budget must raise a
    clear budget-related error (not silently pick a wrong tier), and must
    not blame "this machine" when the user budget is the binding constraint.
    """
    _isolate_fleet_env(monkeypatch)
    monkeypatch.setattr(setup, "_apply_fleet_to_environ", lambda c: None)
    env_path = tmp_path / "worker.env"
    env_path.write_text(
        "\n".join(
            [
                "OLLAMA_FLEET_SERVERS=1",
                "OLLAMA_FLEET_PARALLEL=1",
                "WORKER_MAX_SLOTS=1",
                "OLLAMA_FLEET_W_ALL_BYTES=21474836480",
                "OLLAMA_FLEET_W_PEAK_BYTES=12884901888",
                "WORKER_MODEL_MEMORY_BUDGET_GB=1",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    spec = SystemSpec(
        gpu_count=1,
        vram_bytes=(8 * 1024**3,),
        system_ram_bytes=32 * 1024**3,
        cpu_physical=6,
        cpu_logical=12,
    )
    try:
        setup.ensure_fleet_config(interactive=False, env_path=env_path, spec=spec)
    except RuntimeError as exc:
        message = str(exc)
        assert "WORKER_MODEL_MEMORY_BUDGET_GB" in message
        assert "budget" in message.lower()
    else:
        raise AssertionError("expected RuntimeError: 1 GB budget cannot fit a 12 GB peak model")


def test_ensure_fleet_config_loads_from_env(tmp_path, monkeypatch):
    _isolate_fleet_env(monkeypatch)
    monkeypatch.setattr(setup, "_apply_fleet_to_environ", lambda c: None)
    env_path = tmp_path / "worker.env"
    env_path.write_text(
        "\n".join(
            [
                "OLLAMA_FLEET_SERVERS=2",
                "OLLAMA_FLEET_PARALLEL=3",
                "WORKER_MAX_SLOTS=5",
                "OLLAMA_FLEET_W_ALL_BYTES=2147483648",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    spec = SystemSpec(
        gpu_count=1,
        vram_bytes=(8 * 1024**3,),
        system_ram_bytes=31 * 1024**3,
        cpu_physical=6,
        cpu_logical=12,
    )
    monkeypatch.setattr(setup.models, "estimate_w_peak_bytes", lambda: 1_200_000_000)
    cfg = setup.ensure_fleet_config(interactive=False, env_path=env_path, spec=spec)
    assert cfg.num_servers == 2
    assert cfg.parallel == 3
    assert cfg.max_slots == 5
    assert cfg.w_all_bytes == 2147483648
    assert cfg.memory_tier == "warm_stack"


def test_pids_from_fuser_output_ignores_port_number():
    text = "11434/tcp:            4321 8765\n"
    assert setup._pids_from_fuser_output(text, port=11434) == [4321, 8765]


def test_pids_from_fuser_output_fallback_still_excludes_port():
    text = "Cannot open a network namespace.\n11434 9999\n"
    assert setup._pids_from_fuser_output(text, port=11434) == [9999]


def test_coerce_pid_rejects_overflow_values():
    assert setup._coerce_pid(2**31) is None
    assert setup._coerce_pid(2**32 - 1) is None
    assert setup._coerce_pid(0) is None
    assert setup._coerce_pid(-1) is None
    assert setup._coerce_pid(12345) == 12345


def test_kill_all_ollama_servers_ignores_overflow_pids(monkeypatch):
    calls = {"count": 0}

    def fake_find():
        calls["count"] += 1
        return [2**31 + 5, 4242] if calls["count"] == 1 else []

    monkeypatch.setattr(setup, "_stop_snap_ollama", lambda: None)
    monkeypatch.setattr(setup, "_stop_systemd_ollama", lambda: None)
    monkeypatch.setattr(setup, "_find_ollama_serve_pids", fake_find)
    monkeypatch.setattr(setup, "_pids_listening_on_port", lambda _port: [])
    killed = []
    monkeypatch.setattr(setup, "_signal_pid", lambda pid, sig: killed.append((pid, sig)))
    setup.kill_all_ollama_servers(timeout_sec=0.05)
    assert killed == [(4242, setup.signal.SIGTERM)]


def test_kill_all_ollama_servers_sends_sigterm(monkeypatch):
    calls = {"count": 0}

    def fake_find():
        calls["count"] += 1
        return [100, 200] if calls["count"] == 1 else []

    monkeypatch.setattr(setup, "_stop_snap_ollama", lambda: None)
    monkeypatch.setattr(setup, "_stop_systemd_ollama", lambda: None)
    monkeypatch.setattr(setup, "_pids_listening_on_port", lambda _port: [])
    monkeypatch.setattr(setup, "_find_ollama_serve_pids", fake_find)
    killed = []
    monkeypatch.setattr(setup, "_signal_pid", lambda pid, sig: killed.append((pid, sig)))
    setup.kill_all_ollama_servers(timeout_sec=0.2)
    assert (100, setup.signal.SIGTERM) in killed
    assert (200, setup.signal.SIGTERM) in killed


def test_ensure_ports_free_raises_when_still_busy(monkeypatch):
    monkeypatch.setattr(setup, "_ports_in_use", lambda ports: ports)
    try:
        setup._ensure_ports_free([11434], timeout_sec=0.2)
    except RuntimeError as exc:
        assert "11434" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")


def test_reset_ollama_fleet_kills_before_start(monkeypatch):
    spec = SystemSpec(
        gpu_count=1,
        vram_bytes=(8 * 1024**3,),
        system_ram_bytes=31 * 1024**3,
        cpu_physical=6,
        cpu_logical=12,
    )
    cfg = FleetConfig(
        num_servers=1,
        parallel=1,
        max_slots=1,
        w_all_bytes=2 * 1024**3,
        c_slot_bytes=int(0.4 * 1024**3),
    )
    calls: list[str] = []

    monkeypatch.setattr(setup, "kill_all_ollama_servers", lambda **kw: calls.append("kill"))
    monkeypatch.setattr(setup, "_ensure_ports_free", lambda ports, **kw: calls.append("wait"))
    monkeypatch.setattr(setup, "start_fleet", lambda c, s: calls.extend(["start"]) or ["proc"])
    supervisor = setup.reset_ollama_fleet(cfg, spec)
    assert calls == ["kill", "wait", "start"]
    assert isinstance(supervisor, FleetSupervisor)
    assert supervisor.processes == ["proc"]
