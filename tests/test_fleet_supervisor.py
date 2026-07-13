import subprocess

import httpx
import pytest

from worker.fleet.config import FleetConfig
from worker.fleet.supervisor import FleetSupervisor
from worker.probe import SystemSpec


def _spec():
    return SystemSpec(
        gpu_count=1,
        vram_bytes=(8 * 1024**3,),
        system_ram_bytes=32 * 1024**3,
        cpu_physical=6,
        cpu_logical=12,
    )


class _FakeProc:
    def __init__(self, *, returncode: int | None = None) -> None:
        self._returncode = returncode

    def poll(self):
        return self._returncode

    def terminate(self):
        self._returncode = 0

    def wait(self, timeout=None):
        return 0

    def kill(self):
        self._returncode = 0


def test_supervisor_restart_if_unhealthy_restarts_dead_process(monkeypatch):
    cfg = FleetConfig(num_servers=1, parallel=1, max_slots=1)
    supervisor = FleetSupervisor(cfg, _spec())
    dead = _FakeProc(returncode=1)
    new_proc = _FakeProc(returncode=None)
    supervisor.attach_started(
        host="http://127.0.0.1:11434",
        port=11434,
        parallel=1,
        gpu_index=0,
        max_loaded_models=None,
        proc=dead,  # type: ignore[arg-type]
    )

    restarted: list[int] = []

    def fake_start(**kwargs):
        restarted.append(kwargs["port"])
        return new_proc  # type: ignore[return-value]

    monkeypatch.setattr("worker.fleet.setup.start_ollama_server", fake_start)
    monkeypatch.setattr("worker.fleet.supervisor._api_reachable", lambda host: False)

    assert supervisor.restart_if_unhealthy("http://127.0.0.1:11434") is True
    assert restarted == [11434]
    assert supervisor.processes[0] is new_proc


def test_supervisor_skips_restart_when_healthy(monkeypatch):
    cfg = FleetConfig(num_servers=1, parallel=1, max_slots=1)
    supervisor = FleetSupervisor(cfg, _spec())
    alive = _FakeProc(returncode=None)
    supervisor.attach_started(
        host="http://127.0.0.1:11434",
        port=11434,
        parallel=1,
        gpu_index=0,
        max_loaded_models=None,
        proc=alive,  # type: ignore[arg-type]
    )
    monkeypatch.setattr("worker.fleet.supervisor._api_reachable", lambda host: True)
    monkeypatch.setattr(
        "worker.fleet.setup.start_ollama_server",
        lambda **kwargs: pytest.fail("should not restart"),
    )
    assert supervisor.restart_if_unhealthy("http://127.0.0.1:11434") is False


def test_supervisor_does_not_restart_alive_process_when_api_slow(monkeypatch):
    cfg = FleetConfig(num_servers=1, parallel=1, max_slots=1)
    supervisor = FleetSupervisor(cfg, _spec())
    alive = _FakeProc(returncode=None)
    supervisor.attach_started(
        host="http://127.0.0.1:11434",
        port=11434,
        parallel=1,
        gpu_index=0,
        max_loaded_models=None,
        proc=alive,  # type: ignore[arg-type]
    )
    monkeypatch.setattr("worker.fleet.supervisor._api_reachable", lambda host: False)
    monkeypatch.setattr(
        "worker.fleet.setup.start_ollama_server",
        lambda **kwargs: pytest.fail("should not restart a busy server"),
    )
    assert supervisor.restart_if_unhealthy("http://127.0.0.1:11434") is False


def test_router_retries_after_supervisor_restart(monkeypatch):
    from worker.router import Backend, ModelRouter
    from worker.router.server import start_router_server

    router = ModelRouter(
        [Backend(host="http://127.0.0.1:11434", models={"gemma3:1b"}, parallel=1)]
    )
    cfg = FleetConfig(num_servers=1, parallel=1, max_slots=1)
    supervisor = FleetSupervisor(cfg, _spec())
    calls = {"chat": 0, "restart": 0}

    def fake_chat(host, *, timeout_sec, **kwargs):
        calls["chat"] += 1
        if calls["chat"] == 1:
            raise httpx.ConnectError("connection refused", request=httpx.Request("POST", host))
        return {
            "model": kwargs["model"],
            "message": {"role": "assistant", "content": "{}"},
            "done": True,
        }

    monkeypatch.setattr("worker.router.server.ollama_chat_http", fake_chat)
    monkeypatch.setattr(
        supervisor,
        "restart_if_unhealthy",
        lambda host: calls.__setitem__("restart", calls["restart"] + 1) or True,
    )

    thread = start_router_server(
        router,
        "127.0.0.1",
        0,
        fleet_supervisor=supervisor,
    )
    base_url = f"http://127.0.0.1:{thread._port}"
    try:
        response = httpx.post(
            f"{base_url}/v1/chat",
            json={
                "model": "gemma3:1b",
                "messages": [{"role": "user", "content": "hi"}],
            },
            timeout=30.0,
        )
        assert response.status_code == 200
        assert calls["chat"] == 2
        assert calls["restart"] == 1
    finally:
        thread._server.shutdown()
        thread._server.server_close()
        thread.join(timeout=2.0)
