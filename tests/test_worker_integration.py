from fastapi.testclient import TestClient

from coordinator.annotation_store import InMemoryAnnotationStore
from coordinator.api import create_app
from coordinator.job_store import JobStore
from coordinator.worker_registry import WorkerRegistry
from worker import agent
from worker.client import CoordinatorClient
from worker.config import WorkerConfig


def _config():
    return WorkerConfig(
        coordinator_url="http://testserver",
        worker_api_token="tok",
        worker_name="itest",
        hostname="itest",
        dedicated_memory_bytes=42_000_000_000,
        total_memory_bytes=64_000_000_000,
        max_slots=1,
        agent_version="0.1.0",
    )


def _client_and_store(tmp_path):
    db_path = tmp_path / "jobs.sqlite3"
    store = JobStore(db_path)
    registry = WorkerRegistry(db_path)
    app = create_app(
        job_store=store,
        annotation_store=InMemoryAnnotationStore(),
        worker_registry=registry,
        start_worker=False,
        worker_api_token="tok",
    )
    return TestClient(app), store


def test_worker_registers_and_appears_in_health(tmp_path):
    http, _ = _client_and_store(tmp_path)
    coordinator = CoordinatorClient(_config(), http_client=http)
    coordinator.register()
    health = http.get("/health").json()
    assert health["workers"]["total"] == 1
    assert health["workers"]["connected"] == 1


def test_worker_agent_completes_job_end_to_end(tmp_path, monkeypatch):
    monkeypatch.setattr(agent, "_memory_available_bytes", lambda: 1 << 62)
    monkeypatch.setattr(agent, "_models_ready", lambda: True)
    http, store = _client_and_store(tmp_path)
    coordinator = CoordinatorClient(_config(), http_client=http)
    worker_id = coordinator.register()
    assert worker_id

    job = store.create_job(
        {
            "profile": "mtb-h37rv",
            "locus": "Rv0001",
            "cache_dir": "./.cache",
            "output_dir": "gen_json",
            "profile_config": {"profile_id": "mtb-h37rv", "source": "user"},
        }
    )

    executed = {}

    def fake_execute(request):
        executed.update(request)
        return {"annotation": {"gene_id": "Rv0001"}, "output_path": "gen_json/gen_Rv0001.json"}

    did_work = agent.run_once(coordinator, _config(), active_jobs=0, execute=fake_execute)
    assert did_work is True
    # profile_config (exclude=True on the model) must survive the claim round-trip.
    assert executed["profile_config"] == {"profile_id": "mtb-h37rv", "source": "user"}

    completed = store.get_job(job["id"])
    assert completed["status"] == "completed"
    assert completed["result"]["annotation"]["gene_id"] == "Rv0001"
    assert completed["output_path"] == "gen_json/gen_Rv0001.json"
    assert completed["worker_id"] == worker_id

    # Queue now empty: a second pass does no work.
    assert agent.run_once(coordinator, _config(), active_jobs=0, execute=fake_execute) is False
