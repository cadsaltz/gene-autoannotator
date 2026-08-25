from types import SimpleNamespace

from dispatcher.loop import (
    DispatcherConfig,
    dispatch_once,
    plan_launches,
)


def test_plan_launches_respects_queue_and_available_capacity():
    assert plan_launches(queued=5, inflight=2, max_inflight=4) == 2
    assert plan_launches(queued=0, inflight=0, max_inflight=4) == 0
    assert plan_launches(queued=10, inflight=4, max_inflight=4) == 0
    assert plan_launches(queued=10, inflight=5, max_inflight=4) == 0


def test_dispatch_once_peeks_counts_and_submits_without_claiming():
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
            return SimpleNamespace(stdout="101\n102\n")
        return SimpleNamespace(stdout="Submitted batch job 103\n")

    launched = dispatch_once(
        DispatcherConfig(
            backend_url="https://backend.example/",
            worker_api_token="secret",
            max_inflight=4,
            sbatch_script="/opt/gene-autoannotator/worker-run.sbatch",
        ),
        http_get=http_get,
        command_runner=run,
        user="alice",
    )

    assert launched == 2
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
            ["sbatch", "/opt/gene-autoannotator/worker-run.sbatch"],
            {"check": True},
        ),
        (
            ["sbatch", "/opt/gene-autoannotator/worker-run.sbatch"],
            {"check": True},
        ),
    ]


def test_dispatcher_config_accepts_legacy_coordinator_url(monkeypatch):
    monkeypatch.delenv("BACKEND_URL", raising=False)
    monkeypatch.setenv("COORDINATOR_URL", "https://legacy.example/")
    monkeypatch.setenv("WORKER_API_TOKEN", "secret")
    monkeypatch.setenv("DISPATCHER_MAX_INFLIGHT", "3")
    monkeypatch.setenv("DISPATCHER_SBATCH_SCRIPT", "/tmp/worker-run.sbatch")

    config = DispatcherConfig.from_env()

    assert config == DispatcherConfig(
        backend_url="https://legacy.example",
        worker_api_token="secret",
        max_inflight=3,
        sbatch_script="/tmp/worker-run.sbatch",
    )
