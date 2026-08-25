import argparse
import json
import sys

import pytest
from worker import run
from worker import __main__ as worker_main
from worker.config import WorkerConfig


def _config(*, worker_name="node-a", hostname="node-a", max_slots=4):
    return WorkerConfig(
        coordinator_url="https://coordinator.example",
        worker_api_token="secret",
        worker_name=worker_name,
        hostname=hostname,
        dedicated_memory_bytes=64 * 1024**3,
        total_memory_bytes=128 * 1024**3,
        max_slots=max_slots,
        agent_version="test",
        heartbeat_seconds=15,
    )


def test_run_loads_worker_env_before_config(monkeypatch):
    calls = []

    def fake_ensure_worker_env(**kwargs):
        calls.append(("ensure_worker_env", kwargs))
        monkeypatch.setenv("WORKER_API_TOKEN", "from-worker-env")

    def fake_load_config():
        calls.append(("load_config", {}))
        assert run.os.environ["WORKER_API_TOKEN"] == "from-worker-env"
        return _config()

    class FakeClient:
        def __init__(self, _config):
            pass

        def register(self):
            return "worker-1"

        def claim(self, _free_slots):
            return None

    monkeypatch.delenv("WORKER_API_TOKEN", raising=False)
    monkeypatch.setattr(run, "ensure_worker_env", fake_ensure_worker_env)
    monkeypatch.setattr(run, "load_config", fake_load_config)
    monkeypatch.setattr(run, "CoordinatorClient", FakeClient)

    assert run.main(argparse.Namespace(claim_one=True, job_file=None)) == 0
    assert calls == [
        (
            "ensure_worker_env",
            {"interactive": False, "skip_fleet_config": True},
        ),
        ("load_config", {}),
    ]


def test_run_claim_one_exits_clean_when_no_job(monkeypatch):
    calls = {"register": 0, "claim": [], "execute": 0, "bootstrap": 0}

    class FakeClient:
        def __init__(self, _config):
            pass

        def register(self):
            calls["register"] += 1
            return "worker-1"

        def claim(self, free_slots):
            calls["claim"].append(free_slots)
            return None

    monkeypatch.setattr(run, "load_config", _config)
    monkeypatch.setattr(run, "CoordinatorClient", FakeClient)
    monkeypatch.setattr(
        run,
        "_bootstrap_local_fleet",
        lambda: calls.__setitem__("bootstrap", calls["bootstrap"] + 1),
        raising=False,
    )
    monkeypatch.setattr(
        run,
        "_execute_job",
        lambda *_args, **_kwargs: calls.__setitem__("execute", calls["execute"] + 1),
    )

    rc = run.main(argparse.Namespace(claim_one=True, job_file=None))

    assert rc == 0
    assert calls == {"register": 1, "claim": [1], "execute": 0, "bootstrap": 0}


def test_run_claim_one_registers_ephemeral_single_slot_worker(monkeypatch):
    registered = []

    class FakeClient:
        def __init__(self, config):
            registered.append(config)

        def register(self):
            return "worker-1"

        def claim(self, _free_slots):
            return None

    monkeypatch.setenv("SLURM_JOB_ID", "98765")
    monkeypatch.setattr(run, "load_config", _config)
    monkeypatch.setattr(run, "CoordinatorClient", FakeClient)

    assert run.main(argparse.Namespace(claim_one=True, job_file=None)) == 0
    assert len(registered) == 1
    assert registered[0].worker_name == "node-a-slurm-98765"
    assert registered[0].max_slots == 1


def test_run_claim_one_completes_claimed_job(monkeypatch):
    completed = []
    bootstrapped = []

    class FakeClient:
        def __init__(self, _config):
            pass

        def register(self):
            return "worker-1"

        def claim(self, free_slots):
            assert free_slots == 1
            return {
                "job_id": "job-1",
                "request": {"profile": "mtb-h37rv", "locus": "Rv0001"},
            }

        def complete(self, job_id, result):
            completed.append((job_id, result))

        def fail(self, job_id, error, retryable):
            raise AssertionError(f"unexpected failure: {job_id} {error} {retryable}")

    monkeypatch.setattr(run, "load_config", _config)
    monkeypatch.setattr(run, "CoordinatorClient", FakeClient)
    monkeypatch.setattr(
        run,
        "_bootstrap_local_fleet",
        lambda: bootstrapped.append(True) or (argparse.Namespace(max_slots=1), None, None),
        raising=False,
    )
    monkeypatch.setattr(
        run,
        "_execute_job",
        lambda request, **kwargs: {
            "locus": request["locus"],
            "job_id": kwargs["job_id"],
        },
    )

    rc = run.main(argparse.Namespace(claim_one=True, job_file=None))

    assert rc == 0
    assert bootstrapped == [True]
    assert completed == [("job-1", {"locus": "Rv0001", "job_id": "job-1"})]


def test_run_claim_one_fails_claimed_job_and_exits_nonzero(monkeypatch):
    failed = []

    class FakeClient:
        def __init__(self, _config):
            pass

        def register(self):
            return "worker-1"

        def claim(self, _free_slots):
            return {
                "job_id": "job-1",
                "request": {"profile": "mtb-h37rv", "locus": "Rv0001"},
            }

        def complete(self, job_id, result):
            raise AssertionError(f"unexpected completion: {job_id} {result}")

        def fail(self, job_id, error, retryable):
            failed.append((job_id, error, retryable))

    monkeypatch.setattr(run, "load_config", _config)
    monkeypatch.setattr(run, "CoordinatorClient", FakeClient)
    monkeypatch.setattr(
        run,
        "_bootstrap_local_fleet",
        lambda: (argparse.Namespace(max_slots=1), None, None),
        raising=False,
    )
    monkeypatch.setattr(
        run,
        "_execute_job",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("annotation failed")),
    )

    rc = run.main(argparse.Namespace(claim_one=True, job_file=None))

    assert rc == 1
    assert failed == [("job-1", "annotation failed", True)]


def test_run_claim_one_fails_claimed_job_when_fleet_bootstrap_fails(monkeypatch):
    failed = []

    class FakeClient:
        def __init__(self, _config):
            pass

        def register(self):
            return "worker-1"

        def claim(self, _free_slots):
            return {
                "job_id": "job-1",
                "request": {"profile": "mtb-h37rv", "locus": "Rv0001"},
            }

        def fail(self, job_id, error, retryable):
            failed.append((job_id, error, retryable))

    monkeypatch.setattr(run, "load_config", _config)
    monkeypatch.setattr(run, "CoordinatorClient", FakeClient)
    monkeypatch.setattr(
        run,
        "_bootstrap_local_fleet",
        lambda: (_ for _ in ()).throw(RuntimeError("fleet startup failed")),
    )

    rc = run.main(argparse.Namespace(claim_one=True, job_file=None))

    assert rc == 1
    assert failed == [("job-1", "fleet startup failed", True)]


def test_run_job_file_skips_register_and_claim(monkeypatch, tmp_path):
    job_path = tmp_path / "job.json"
    job_path.write_text(
        json.dumps(
            {
                "job_id": "job-file-1",
                "request": {"profile": "mtb-h37rv", "locus": "Rv0002"},
            }
        ),
        encoding="utf-8",
    )
    calls = {"register": 0, "claim": 0, "completed": []}

    class FakeClient:
        def __init__(self, _config):
            pass

        def register(self):
            calls["register"] += 1

        def claim(self, _free_slots):
            calls["claim"] += 1

        def complete(self, job_id, result):
            calls["completed"].append((job_id, result))

        def fail(self, job_id, error, retryable):
            raise AssertionError(f"unexpected failure: {job_id} {error} {retryable}")

    monkeypatch.setattr(run, "load_config", _config)
    monkeypatch.setattr(run, "CoordinatorClient", FakeClient)
    monkeypatch.setattr(
        run,
        "_bootstrap_local_fleet",
        lambda: (argparse.Namespace(max_slots=1), None, None),
        raising=False,
    )
    monkeypatch.setattr(
        run,
        "_execute_job",
        lambda request, **_kwargs: {"locus": request["locus"]},
    )

    rc = run.main(argparse.Namespace(claim_one=False, job_file=str(job_path)))

    assert rc == 0
    assert calls == {
        "register": 0,
        "claim": 0,
        "completed": [("job-file-1", {"locus": "Rv0002"})],
    }


@pytest.mark.parametrize(
    ("cli_args", "expected"),
    [
        (["--claim-one"], {"claim_one": True, "job_file": None}),
        (["--job-file", "/tmp/job.json"], {"claim_one": False, "job_file": "/tmp/job.json"}),
    ],
)
def test_worker_run_cli_dispatches_one_shot_mode(monkeypatch, cli_args, expected):
    captured = {}

    def fake_run_main(args):
        captured.update(vars(args))
        return 7

    monkeypatch.setattr(run, "main", fake_run_main)
    monkeypatch.setattr(sys, "argv", ["worker", "run", *cli_args])

    with pytest.raises(SystemExit) as exc_info:
        worker_main.main()

    assert exc_info.value.code == 7
    assert captured["claim_one"] is expected["claim_one"]
    assert captured["job_file"] == expected["job_file"]
