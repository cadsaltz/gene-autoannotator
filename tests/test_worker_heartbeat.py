import time

from worker import agent
from tests.test_worker_agent import _config


def test_heartbeat_thread_runs_during_execute(monkeypatch):
    heartbeats = []

    class Client:
        worker_id = "w1"

        def heartbeat(self, **kw):
            heartbeats.append(time.time())
            return {"required_version": None, "drain": False}

        def progress(self, *a):
            pass

        def complete(self, *a):
            pass

        def claim(self, n):
            return {
                "job_id": "j1",
                "request": {"profile": "p", "locus": "L"},
                "lease_expires_at": "x",
            }

    def slow_execute(_):
        time.sleep(0.35)
        return {"output_path": "x"}

    monkeypatch.setattr(agent, "_memory_available_bytes", lambda: 1 << 62)
    monkeypatch.setattr(agent, "_models_ready", lambda: True)
    monkeypatch.setattr(agent.capacity, "can_admit", lambda *_a, **_k: True)
    agent.run_once(
        Client(),
        _config(),
        active_jobs=0,
        execute=slow_execute,
        heartbeat_interval=0.1,
    )
    assert len(heartbeats) >= 2
