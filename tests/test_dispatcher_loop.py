from types import SimpleNamespace

from dispatcher.loop import (
    DispatcherConfig,
    REPO_ROOT,
    dispatch_once,
    plan_launches,
)


def test_plan_launches_at_most_one_worker():
    assert plan_launches(20000, 0) == 1
    assert plan_launches(20000, 1) == 0
    assert plan_launches(0, 0) == 0
    assert plan_launches(3, 0) == 1
    assert plan_launches(3, 0, max_inflight=0) == 0


def test_dispatch_once_submits_one_sbatch_when_queue_has_work():
    requests = []
    commands = []

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"queued": 5}

    def http_get(url, **kwargs):
        requests.append((url, kwargs))
        return Response()

    def run(command, **kwargs):
        commands.append((command, kwargs))
        if command[0] == "squeue":
            return SimpleNamespace(stdout="")
        return SimpleNamespace(stdout="Submitted batch job 103\n")

    launched = dispatch_once(
        DispatcherConfig(
            backend_url="https://backend.example/",
            worker_api_token="secret",
            max_inflight=4,
            max_jobs_per_worker=500,
            sbatch_script="/opt/gene-autoannotator/worker-run.sbatch",
        ),
        http_get=http_get,
        command_runner=run,
        user="alice",
    )

    assert launched == 1
    assert requests == [
        (
            "https://backend.example/jobs/queue-summary",
            {
                "headers": {"Authorization": "Bearer secret"},
                "timeout": 30.0,
            },
        )
    ]
    assert commands == [
        (
            [
                "squeue",
                "--noheader",
                "--user",
                "alice",
                "--name",
                "gene-autoannotator-run",
                "--format=%i",
            ],
            {"check": True, "capture_output": True, "text": True},
        ),
        (
            [
                "sbatch",
                f"--export=ALL,GAA_REPO_ROOT={REPO_ROOT},WORKER_RUN_MAX_JOBS=500",
                "/opt/gene-autoannotator/worker-run.sbatch",
            ],
            {"check": True},
        ),
    ]
    assert REPO_ROOT.is_absolute()


def test_dispatch_once_submits_no_sbatch_when_worker_inflight():
    commands = []

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"queued": 5}

    def http_get(url, **kwargs):
        return Response()

    def run(command, **kwargs):
        commands.append((command, kwargs))
        if command[0] == "squeue":
            return SimpleNamespace(stdout="101\n")
        return SimpleNamespace(stdout="Submitted batch job 103\n")

    launched = dispatch_once(
        DispatcherConfig(
            backend_url="https://backend.example/",
            worker_api_token="secret",
            max_inflight=4,
            max_jobs_per_worker=500,
            sbatch_script="/opt/gene-autoannotator/worker-run.sbatch",
        ),
        http_get=http_get,
        command_runner=run,
        user="alice",
    )

    assert launched == 0
    assert len(commands) == 1
    assert commands[0][0][0] == "squeue"


def test_dispatcher_config_requires_backend_url(monkeypatch):
    monkeypatch.delenv("BACKEND_URL", raising=False)
    monkeypatch.setenv("WORKER_API_TOKEN", "secret")
    monkeypatch.setenv("DISPATCHER_MAX_INFLIGHT", "3")
    monkeypatch.setenv("DISPATCHER_SBATCH_SCRIPT", "/tmp/worker-run.sbatch")

    try:
        DispatcherConfig.from_env()
        raise AssertionError("expected RuntimeError")
    except RuntimeError as exc:
        assert "BACKEND_URL" in str(exc)


def test_dispatcher_config_reads_backend_url(monkeypatch):
    monkeypatch.setenv("BACKEND_URL", "https://api.example/")
    monkeypatch.setenv("WORKER_API_TOKEN", "secret")
    monkeypatch.setenv("DISPATCHER_MAX_INFLIGHT", "3")
    monkeypatch.setenv("DISPATCHER_SBATCH_SCRIPT", "/tmp/worker-run.sbatch")

    config = DispatcherConfig.from_env()

    assert config == DispatcherConfig(
        backend_url="https://api.example",
        worker_api_token="secret",
        max_inflight=3,
        max_jobs_per_worker=500,
        sbatch_script="/tmp/worker-run.sbatch",
    )
