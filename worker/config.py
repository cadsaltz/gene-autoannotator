import os
import socket
from dataclasses import dataclass

from worker import capacity
from worker.fleet.config import FleetConfig
from worker.fleet import sizing
from worker.probe import probe_system


@dataclass
class WorkerConfig:
    coordinator_url: str
    worker_api_token: str
    worker_name: str
    hostname: str
    dedicated_memory_bytes: int
    total_memory_bytes: int
    max_slots: int
    agent_version: str
    heartbeat_seconds: int = 15


def _total_memory_bytes():
    try:
        import psutil

        return int(psutil.virtual_memory().total)
    except Exception:  # noqa: BLE001 - fall back to the configured budget.
        return 0


def load_config():
    coordinator_url = os.environ["COORDINATOR_URL"].rstrip("/")
    token = os.environ.get("WORKER_API_TOKEN", "")
    hostname = socket.gethostname()
    worker_name = os.getenv("WORKER_NAME", hostname)
    user_gb = sizing.parse_model_memory_budget_gb(
        os.getenv("WORKER_MODEL_MEMORY_BUDGET_GB")
        or os.getenv("ANNOTATION_MEMORY_BUDGET_GB")
    )
    dedicated_bytes = sizing.effective_model_budget_bytes(
        probe_system(), user_budget_gb=user_gb,
    )
    total_bytes = _total_memory_bytes()
    fleet_keys_present = bool(os.getenv("OLLAMA_FLEET_SERVERS") or os.getenv("OLLAMA_FLEET_PARALLEL"))
    worker_max_slots = os.getenv("WORKER_MAX_SLOTS")
    if fleet_keys_present and worker_max_slots is not None:
        fleet = FleetConfig(
            num_servers=int(os.getenv("OLLAMA_FLEET_SERVERS", "1")),
            parallel=int(os.getenv("OLLAMA_FLEET_PARALLEL", "1")),
            max_slots=int(worker_max_slots),
        )
        slots = capacity.compute_slots_from_fleet(fleet)
    else:
        slots = capacity.compute_slots(dedicated_bytes / (1024**3)) if dedicated_bytes else 0
    return WorkerConfig(
        coordinator_url=coordinator_url,
        worker_api_token=token,
        worker_name=worker_name,
        hostname=hostname,
        dedicated_memory_bytes=dedicated_bytes,
        total_memory_bytes=total_bytes or dedicated_bytes,
        max_slots=slots,
        agent_version=os.getenv("APP_VERSION", "dev"),
        heartbeat_seconds=int(os.getenv("HEARTBEAT_SECONDS", "15")),
    )
