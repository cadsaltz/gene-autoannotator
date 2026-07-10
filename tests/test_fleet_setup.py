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
    monkeypatch.setattr(setup, "_ensure_ports_free", lambda ports, **kw: None)
    procs = setup.start_fleet(cfg, spec)
    assert len(procs) == 2
    assert launched == [(11434, 3, 0), (11435, 3, 1)]


def test_build_ollama_server_env_does_not_inherit_parent_host(monkeypatch):
    monkeypatch.setenv("OLLAMA_HOST", "http://127.0.0.1:11434")
    env = setup._build_ollama_server_env(port=11435, parallel=2, gpu_index=0)
    assert env["OLLAMA_HOST"] == "127.0.0.1:11435"
    assert env["OLLAMA_NUM_PARALLEL"] == "2"
    assert env["CUDA_VISIBLE_DEVICES"] == "0"


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
    monkeypatch.setattr(setup.os, "kill", lambda pid, sig: killed.append((pid, sig)))
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
    procs = setup.reset_ollama_fleet(cfg, spec)
    assert calls == ["kill", "wait", "start"]
    assert procs == ["proc"]
