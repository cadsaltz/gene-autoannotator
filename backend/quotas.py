import logging
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from .access import is_admin

log = logging.getLogger(__name__)

DAILY_WINDOW = timedelta(hours=24)


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        log.warning("Ignoring non-integer %s=%r; using default %d", name, raw, default)
        return default


def daily_window_start() -> str:
    return (datetime.now(UTC) - DAILY_WINDOW).isoformat()


class QuotaExceeded(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class QuotaConfig:
    max_queued: int
    user_max_active: int
    user_max_per_day: int
    user_max_batch: int

    @classmethod
    def from_env(cls) -> "QuotaConfig":
        return cls(
            max_queued=_env_int("MAX_QUEUED_JOBS", 200),
            user_max_active=_env_int("USER_MAX_ACTIVE_JOBS", 20),
            user_max_per_day=_env_int("USER_MAX_JOBS_PER_DAY", 50),
            user_max_batch=_env_int("USER_MAX_BATCH_SIZE", 25),
        )

    def accepting(self, queued: int) -> bool:
        return self.max_queued <= 0 or queued < self.max_queued


def effective_limits(user: dict, config: QuotaConfig) -> dict:
    if is_admin(user):
        return {"max_active": None, "max_per_day": None, "max_batch": None}

    def pick(override, default):
        value = override if override is not None else default
        return value if value > 0 else None

    return {
        "max_active": pick(user.get("quota_max_active"), config.user_max_active),
        "max_per_day": pick(user.get("quota_max_per_day"), config.user_max_per_day),
        "max_batch": pick(user.get("quota_max_batch"), config.user_max_batch),
    }


def check_batch_size(*, user: dict, entry_count: int, config: QuotaConfig) -> None:
    max_batch = effective_limits(user, config)["max_batch"]
    if max_batch is not None and entry_count > max_batch:
        raise QuotaExceeded(
            "batch_limit", f"Batches are limited to {max_batch} genes per submission."
        )


def check_submission(*, user: dict, job_count: int, store, config: QuotaConfig) -> None:
    if is_admin(user):
        return
    limits = effective_limits(user, config)
    check_batch_size(user=user, entry_count=job_count, config=config)
    if config.max_queued > 0 and store.count_queued_jobs() + job_count > config.max_queued:
        raise QuotaExceeded("queue_full", "The queue is full right now. Please try again later.")
    active = store.count_active_for_user(user["id"])
    if limits["max_active"] is not None and active + job_count > limits["max_active"]:
        raise QuotaExceeded(
            "active_limit", f"You can have at most {limits['max_active']} queued or running jobs."
        )
    today = store.count_created_since_for_user(user["id"], daily_window_start())
    if limits["max_per_day"] is not None and today + job_count > limits["max_per_day"]:
        raise QuotaExceeded(
            "daily_limit", f"You can submit at most {limits['max_per_day']} jobs per 24 hours."
        )
