import argparse
import json
import sys

import pytest
from worker import run
from worker import __main__ as worker_main


def test_run_claim_one_exits_clean_when_no_job(monkeypatch):
    calls = {"register": 0, "claim": [], "execute": 0}

    class FakeClient:
        def __init__(self, _config):
            pass

        def register(self):
            calls["register"] += 1
            return "worker-1"

        def claim(self, free_slots):
            calls["claim"].append(free_slots)
            return None

    monkeypatch.setattr(run, "load_config", lambda: argparse.Namespace(max_slots=4))
    monkeypatch.setattr(run, "CoordinatorClient", FakeClient)
    monkeypatch.setattr(
        run,
        "_execute_job",
        lambda *_args, **_kwargs: calls.__setitem__("execute", calls["execute"] + 1),
    )

    rc = run.main(argparse.Namespace(claim_one=True, job_file=None))

    assert rc == 0
    assert calls == {"register": 1, "claim": [1], "execute": 0}


def test_run_claim_one_completes_claimed_job(monkeypatch):
    completed = []

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

    monkeypatch.setattr(
        run,
        "load_config",
        lambda: argparse.Namespace(max_slots=4, heartbeat_seconds=15),
    )
    monkeypatch.setattr(run, "CoordinatorClient", FakeClient)
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

    monkeypatch.setattr(
        run,
        "load_config",
        lambda: argparse.Namespace(max_slots=4, heartbeat_seconds=15),
    )
    monkeypatch.setattr(run, "CoordinatorClient", FakeClient)
    monkeypatch.setattr(
        run,
        "_execute_job",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("annotation failed")),
    )

    rc = run.main(argparse.Namespace(claim_one=True, job_file=None))

    assert rc == 1
    assert failed == [("job-1", "annotation failed", True)]


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

    monkeypatch.setattr(
        run,
        "load_config",
        lambda: argparse.Namespace(max_slots=4, heartbeat_seconds=15),
    )
    monkeypatch.setattr(run, "CoordinatorClient", FakeClient)
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
