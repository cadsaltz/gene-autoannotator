import logging
import os
import sys
import threading
import time

from shared.job_contract import AnnotationJobRequest
from worker import capacity, executor
from worker.client import CoordinatorClient
from worker.config import load_config

log = logging.getLogger(__name__)

PERMANENT_ERROR_MARKERS = ("locus_schema_mismatch", "profile or organism", "name or locus")

_models_ready_flag = False
_draining = False


def _models_ready():
    return _models_ready_flag


def _ensure_models_ready():
    global _models_ready_flag
    from worker import ollama_bootstrap

    log.info("Ensuring Ollama models are available...")
    ollama_bootstrap.ensure_models()
    _models_ready_flag = True


def _memory_available_bytes():
    try:
        import psutil

        return int(psutil.virtual_memory().available)
    except Exception:  # noqa: BLE001 - assume plenty if psutil is missing.
        return 1 << 62


def _cpu_percent():
    try:
        import psutil

        return float(psutil.cpu_percent(interval=None))
    except Exception:  # noqa: BLE001
        return 0.0


def _is_retryable(error_message):
    return not any(marker in error_message for marker in PERMANENT_ERROR_MARKERS)


def _default_execute(request_dict):
    return executor.run_annotation_job(AnnotationJobRequest(**request_dict))


def _should_drain(heartbeat_response, config):
    if heartbeat_response.get("drain"):
        return True
    required_version = heartbeat_response.get("required_version")
    return required_version is not None and required_version != config.agent_version


def run_once(client, config, *, active_jobs, execute, heartbeat_interval=None):
    global _draining
    interval = heartbeat_interval if heartbeat_interval is not None else config.heartbeat_seconds
    free_slots = max(0, config.max_slots - active_jobs)
    if _draining:
        state = "draining"
    elif not _models_ready():
        state = "provisioning"
    else:
        state = "ready"
    heartbeat_response = client.heartbeat(
        active_jobs=active_jobs,
        free_slots=free_slots,
        memory_available_bytes=_memory_available_bytes(),
        cpu_percent=_cpu_percent(),
        state=state,
    )
    if _should_drain(heartbeat_response, config):
        _draining = True
        client.heartbeat(
            active_jobs=active_jobs,
            free_slots=free_slots,
            memory_available_bytes=_memory_available_bytes(),
            cpu_percent=_cpu_percent(),
            state="draining",
        )
    if _draining:
        return False
    if not _models_ready():
        return False
    if free_slots <= 0:
        return False
    if not capacity.can_admit(_memory_available_bytes()):
        return False
    claim = client.claim(free_slots)
    if claim is None:
        return False

    job_id = claim["job_id"]
    job_active_jobs = active_jobs + 1
    job_free_slots = max(0, config.max_slots - job_active_jobs)
    stop_heartbeat = threading.Event()

    def heartbeat_loop():
        while not stop_heartbeat.wait(interval):
            client.heartbeat(
                active_jobs=job_active_jobs,
                free_slots=job_free_slots,
                memory_available_bytes=_memory_available_bytes(),
                cpu_percent=_cpu_percent(),
                state="ready",
            )

    heartbeat_thread = threading.Thread(target=heartbeat_loop, daemon=True)
    heartbeat_thread.start()
    try:
        client.progress(job_id, "running")
        result = execute(claim["request"])
        client.complete(job_id, result)
        log.info("Completed job %s", job_id)
    except Exception as exc:  # noqa: BLE001 - report every failure to the coordinator.
        message = str(exc)
        client.fail(job_id, message, _is_retryable(message))
        log.warning("Job %s failed: %s", job_id, message)
    finally:
        stop_heartbeat.set()
        heartbeat_thread.join(timeout=5)
    return True


def _configure_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s | %(message)s",
        stream=sys.stdout,
        force=True,
    )


def run(poll_seconds=5):
    _configure_logging()
    config = load_config()
    client = CoordinatorClient(config)
    _ensure_models_ready()
    client.register()
    log.info("Registered worker %s (%s slots)", config.worker_name, config.max_slots)
    if config.max_slots <= 0:
        log.warning(
            "Worker registered with 0 slots (ANNOTATION_MEMORY_BUDGET_GB=%s); it will "
            "never claim jobs. Increase the memory budget above one job's requirement.",
            os.getenv("ANNOTATION_MEMORY_BUDGET_GB"),
        )
    while True:
        try:
            did_work = run_once(client, config, active_jobs=0, execute=_default_execute)
        except Exception:  # noqa: BLE001 - survive transient coordinator/network errors.
            log.exception("Worker loop iteration failed; backing off")
            did_work = False
        if _draining:
            log.info("Draining for update; exiting")
            return
        if not did_work:
            log.debug("No work claimed; sleeping %ss", poll_seconds)
            time.sleep(poll_seconds)
