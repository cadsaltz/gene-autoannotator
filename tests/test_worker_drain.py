from worker import agent
from tests.test_worker_agent import _config
import pytest


@pytest.fixture(autouse=True)
def _reset_draining():
    agent._draining = False
    yield


def test_run_once_sets_draining_on_heartbeat_signal(monkeypatch):
    monkeypatch.setattr(agent, "_memory_available_bytes", lambda: 1 << 62)
    monkeypatch.setattr(agent, "_models_ready", lambda: True)

    class Client:
        worker_id = "w1"

        def heartbeat(self, **kw):
            return {"required_version": "2.0.0", "drain": True}

        def claim(self, n):
            raise AssertionError("should not claim")

    agent._draining = False  # reset
    assert agent.run_once(Client(), _config(), active_jobs=0, execute=lambda r: {}) is False
    assert agent._draining is True
    agent._draining = False  # cleanup for other tests
