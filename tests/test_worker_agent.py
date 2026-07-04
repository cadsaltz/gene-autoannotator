from worker import agent
from worker.config import WorkerConfig


class FakeClient:
    def __init__(self, claim_job=None):
        self._claim_job = claim_job
        self.completed = []
        self.failed = []
        self.progress_calls = []

    def heartbeat(self, active_jobs, free_slots, memory_available_bytes, cpu_percent, state):
        return {"required_version": None, "drain": False}

    def claim(self, free_slots):
        return self._claim_job

    def progress(self, job_id, current_step):
        self.progress_calls.append((job_id, current_step))

    def complete(self, job_id, result):
        self.completed.append((job_id, result))

    def fail(self, job_id, error, retryable):
        self.failed.append((job_id, error, retryable))


def _config():
    return WorkerConfig(
        coordinator_url="http://localhost:8000",
        worker_api_token="t",
        worker_name="w1",
        hostname="w1",
        dedicated_memory_bytes=42_000_000_000,
        total_memory_bytes=64_000_000_000,
        max_slots=2,
        agent_version="0.1.0",
    )


def test_run_once_claims_and_completes(monkeypatch):
    monkeypatch.setattr(agent, "_memory_available_bytes", lambda: 1 << 62)
    claim = {
        "job_id": "j1",
        "request": {"profile": "mtb-h37rv", "locus": "Rv0001"},
        "lease_expires_at": "2026-07-03T00:00:00+00:00",
    }
    client = FakeClient(claim_job=claim)

    def fake_execute(request):
        return {"annotation": {"gene_id": "Rv0001"}, "output_path": "x.json"}

    did_work = agent.run_once(client, _config(), active_jobs=0, execute=fake_execute)
    assert did_work is True
    assert client.completed[0][0] == "j1"


def test_run_once_reports_failure(monkeypatch):
    monkeypatch.setattr(agent, "_memory_available_bytes", lambda: 1 << 62)
    claim = {
        "job_id": "j1",
        "request": {"profile": "mtb-h37rv", "locus": "Rv0001"},
        "lease_expires_at": "2026-07-03T00:00:00+00:00",
    }
    client = FakeClient(claim_job=claim)

    def boom(request):
        raise RuntimeError("ollama down")

    agent.run_once(client, _config(), active_jobs=0, execute=boom)
    assert client.failed[0][0] == "j1"


def test_run_once_no_free_slots_skips_claim():
    client = FakeClient(claim_job={"job_id": "should-not-claim"})
    did_work = agent.run_once(client, _config(), active_jobs=2, execute=lambda r: {})
    assert did_work is False
    assert client.completed == []
