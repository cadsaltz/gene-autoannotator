import json

from shared.job_contract import AnnotationJobRequest
from worker import executor


def test_executor_calls_annotation_main_with_request_fields(monkeypatch):
    monkeypatch.setenv("WORKER_JOB_EXECUTION", "inprocess")
    captured = {}

    def fake_main(**kwargs):
        captured.update(kwargs)
        return {"annotation": {"gene_id": "Rv0001"}, "output_path": "gen_json/gen_Rv0001.json"}

    request = AnnotationJobRequest(profile="mtb-h37rv", locus="Rv0001", allow_online_name_lookup=False)
    result = executor.run_annotation_job(request, annotation_main=fake_main)

    assert captured["profile"] == "mtb-h37rv"
    assert captured["locus"] == "Rv0001"
    assert captured["no_online_name_lookup"] is True
    assert result["output_path"] == "gen_json/gen_Rv0001.json"


def test_executor_uses_worker_env_paths_over_request(monkeypatch):
    monkeypatch.setenv("WORKER_JOB_EXECUTION", "inprocess")
    monkeypatch.setenv("WORKER_CACHE_DIR", "/worker/cache")
    monkeypatch.setenv("WORKER_OUTPUT_DIR", "/worker/out")

    captured = {}

    def fake_main(**kwargs):
        captured.update(kwargs)
        return {}

    request = AnnotationJobRequest(
        profile="mtb-h37rv",
        locus="Rv0001",
        cache_dir="/coordinator/cache",
        output_dir="/coordinator/out",
    )
    executor.run_annotation_job(request, annotation_main=fake_main)

    assert captured["cache_dir"] == "/worker/cache"
    assert captured["output_dir"] == "/worker/out"


def test_run_annotation_job_subprocess_sets_job_env(monkeypatch):
    monkeypatch.setenv("WORKER_JOB_EXECUTION", "subprocess")
    monkeypatch.setenv("OLLAMA_ROUTER_URL", "http://127.0.0.1:11499")
    monkeypatch.setenv("AUTOANNOTATION_MODEL_MODE", "fleet")
    monkeypatch.setenv("AUTOANNOTATION_OLLAMA_KEEP_ALIVE", "5m")
    monkeypatch.setenv("WORKER_CACHE_DIR", "/worker/cache")
    monkeypatch.setenv("WORKER_OUTPUT_DIR", "/worker/out")

    captured = {}

    class FakePopen:
        def __init__(self, cmd, **kwargs):
            captured["cmd"] = cmd
            captured["env"] = kwargs["env"]

        def communicate(self):
            return (
                json.dumps(
                    {
                        "annotation": {"gene_id": "Rv0001"},
                        "output_path": "gen_json/gen_Rv0001.json",
                    }
                ),
                "",
            )

        returncode = 0

    monkeypatch.setattr(executor.subprocess, "Popen", FakePopen)

    request = AnnotationJobRequest(profile="mtb-h37rv", locus="Rv0001")
    result = executor.run_annotation_job(request, job_id="job-123")

    assert captured["cmd"][:3] == [executor.sys.executable, "-m", "worker.job_main"]
    assert captured["cmd"][3] == "--request-file"
    assert captured["cmd"][4].endswith(".json")
    assert captured["env"]["ANNOTATION_JOB_ID"] == "job-123"
    assert captured["env"]["OLLAMA_ROUTER_URL"] == "http://127.0.0.1:11499"
    assert captured["env"]["AUTOANNOTATION_MODEL_MODE"] == "fleet"
    assert captured["env"]["AUTOANNOTATION_OLLAMA_KEEP_ALIVE"] == "5m"
    assert captured["env"]["WORKER_CACHE_DIR"] == "/worker/cache"
    assert captured["env"]["WORKER_OUTPUT_DIR"] == "/worker/out"
    assert captured["env"]["WORKER_JOB_EXECUTION"] == "inprocess"
    assert result["output_path"] == "gen_json/gen_Rv0001.json"


def test_terminate_active_jobs_kills_running_subprocess(monkeypatch):
    import threading
    import time

    monkeypatch.setenv("WORKER_JOB_EXECUTION", "subprocess")

    class BlockingPopen:
        def __init__(self, cmd, **kwargs):
            self._terminated = False

        def communicate(self):
            while not self._terminated:
                time.sleep(0.01)
            return ("", "stopped")

        def terminate(self):
            self._terminated = True

        def wait(self, timeout=None):
            return 0

        returncode = -15

    monkeypatch.setattr(executor.subprocess, "Popen", BlockingPopen)

    request = AnnotationJobRequest(profile="mtb-h37rv", locus="Rv0001")

    def run_job():
        try:
            executor.run_annotation_job(request, job_id="job-stop")
        except RuntimeError:
            pass

    thread = threading.Thread(target=run_job)
    thread.start()
    for _ in range(100):
        if executor._active_processes:
            break
        time.sleep(0.01)
    assert "job-stop" in executor._active_processes
    executor.terminate_active_jobs()
    thread.join(timeout=2)
    assert "job-stop" not in executor._active_processes
