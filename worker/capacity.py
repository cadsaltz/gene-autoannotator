import os
from typing import TYPE_CHECKING

DEFAULT_JOB_MEMORY_ESTIMATE_GB = 20.0
DEFAULT_HEADROOM_GB = 4.0
SUBPROCESS_OVERHEAD_BYTES = 2 * 1024**3
_BYTES_PER_GB = 1024 ** 3

if TYPE_CHECKING:
    from worker.fleet.config import FleetConfig


def _job_estimate_gb():
    return float(os.getenv("JOB_MEMORY_ESTIMATE_GB", DEFAULT_JOB_MEMORY_ESTIMATE_GB))


def _headroom_gb():
    return float(os.getenv("WORKER_MEMORY_HEADROOM_GB", DEFAULT_HEADROOM_GB))


def compute_slots(dedicated_gb, *, job_estimate_gb=None, headroom_gb=None):
    job_estimate_gb = _job_estimate_gb() if job_estimate_gb is None else float(job_estimate_gb)
    headroom_gb = _headroom_gb() if headroom_gb is None else float(headroom_gb)
    usable = dedicated_gb - headroom_gb
    if usable < job_estimate_gb:
        return 0
    return int(usable // job_estimate_gb)


def compute_slots_from_fleet(fleet: "FleetConfig") -> int:
    return int(fleet.max_slots)


def can_admit(memory_available_bytes, *, job_estimate_gb=None, headroom_gb=None):
    return memory_available_bytes >= SUBPROCESS_OVERHEAD_BYTES
