import os
import socket
from dataclasses import dataclass

from worker import capacity


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
    dedicated_gb = float(os.getenv("ANNOTATION_MEMORY_BUDGET_GB", "0"))
    dedicated_bytes = int(dedicated_gb * (1024 ** 3))
    total_bytes = _total_memory_bytes()
    slots = capacity.compute_slots(dedicated_gb) if dedicated_gb else 0
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
