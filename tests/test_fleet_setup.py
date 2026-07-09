from worker.fleet.config import FleetConfig
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
    recommendation = FleetConfig(
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

    def fake_start(*, port, parallel, gpu_index):
        launched.append((port, parallel, gpu_index))
        return FakePopen()

    monkeypatch.setattr(setup, "start_ollama_server", fake_start)
    procs = setup.start_fleet(cfg, spec)
    assert len(procs) == 2
    assert launched == [(11434, 3, 0), (11435, 3, 1)]


def test_ensure_fleet_config_loads_from_env(tmp_path, monkeypatch):
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
    monkeypatch.setattr(
        setup,
        "probe_system",
        lambda: (_ for _ in ()).throw(AssertionError("probe should not run")),
    )
    cfg = setup.ensure_fleet_config(interactive=False, env_path=env_path)
    assert cfg.num_servers == 2
    assert cfg.parallel == 3
    assert cfg.max_slots == 5
    assert cfg.w_all_bytes == 2147483648
