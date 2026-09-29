import logging
import math
import os
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from . import email_sender

log = logging.getLogger(__name__)

RESEND_INTERVAL = timedelta(hours=6)
FAILURE_WINDOW = timedelta(hours=1)
MIN_FINISHED_FOR_FAILURE_RATE = 5
SUBJECT_PREFIX = "[Gene Autoannotator]"
FOOTER = (
    "\n\nReview details in the admin console. This alert repeats at most every "
    "6 hours while the condition persists."
)

DEFAULT_CHECK_SECONDS = 300
MAX_CHECK_SECONDS = 86400
DEFAULT_QUEUE_DEPTH = 50
DEFAULT_NO_WORKER_MINUTES = 15
DEFAULT_FAILURE_RATE = 0.5


def _env_number(name, default, cast):
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = float(raw.strip())
    except ValueError:
        value = None
    if value is None or not math.isfinite(value):
        log.warning("Ignoring invalid %s=%r; using default %s", name, raw, default)
        return default
    return cast(value)


def _fmt(value):
    return f"{value:g}"


@dataclass(frozen=True)
class Alert:
    key: str
    subject: str
    body: str


@dataclass(frozen=True)
class AlertConfig:
    check_seconds: float = DEFAULT_CHECK_SECONDS
    queue_depth: int = DEFAULT_QUEUE_DEPTH
    no_worker_minutes: float = DEFAULT_NO_WORKER_MINUTES
    failure_rate: float = DEFAULT_FAILURE_RATE
    offline_after_seconds: int = 60

    @classmethod
    def from_env(cls, *, offline_after_seconds=60) -> "AlertConfig":
        return cls(
            # Event.wait raises OverflowError beyond threading.TIMEOUT_MAX.
            check_seconds=min(
                _env_number("ALERT_CHECK_SECONDS", DEFAULT_CHECK_SECONDS, float),
                MAX_CHECK_SECONDS,
            ),
            queue_depth=_env_number("ALERT_QUEUE_DEPTH", DEFAULT_QUEUE_DEPTH, int),
            no_worker_minutes=_env_number(
                "ALERT_NO_WORKER_MINUTES", DEFAULT_NO_WORKER_MINUTES, float
            ),
            failure_rate=_env_number("ALERT_FAILURE_RATE", DEFAULT_FAILURE_RATE, float),
            offline_after_seconds=offline_after_seconds,
        )

    @property
    def enabled(self) -> bool:
        return self.check_seconds > 0


def _online_workers(workers, config) -> int:
    # Draining workers are exempt from going offline, so counting them would let a
    # crashed draining worker silence the no-worker alert forever.
    states = workers.summary(offline_after_seconds=config.offline_after_seconds)["states"]
    return states.get("ready", 0) + states.get("provisioning", 0)


def next_no_worker_since(*, store, workers, now, config, previous):
    """Return when the "jobs queued, no worker online" condition began, or None."""
    if config.no_worker_minutes <= 0:
        return None
    if store.count_queued_jobs() > 0 and _online_workers(workers, config) == 0:
        return previous or now
    return None


def evaluate_alerts(*, store, workers, now, config, no_worker_since=None) -> list[Alert]:
    queued = store.count_queued_jobs()
    online = _online_workers(workers, config)
    alerts = []

    if config.queue_depth > 0 and queued >= config.queue_depth:
        alerts.append(
            Alert(
                key="queue_depth",
                subject=f"{SUBJECT_PREFIX} Queue backlog: {queued} jobs waiting",
                body=(
                    f"{queued} jobs are queued (alert threshold: {config.queue_depth}).\n"
                    f"Workers online: {online}."
                    f"{FOOTER}"
                ),
            )
        )

    if (
        config.no_worker_minutes > 0
        and no_worker_since is not None
        and queued > 0
        and online == 0
        and now - no_worker_since >= timedelta(minutes=config.no_worker_minutes)
    ):
        elapsed = int((now - no_worker_since).total_seconds() // 60)
        alerts.append(
            Alert(
                key="no_worker",
                subject=f"{SUBJECT_PREFIX} No workers online with {queued} jobs queued",
                body=(
                    f"{queued} jobs are queued and no worker has been online for "
                    f"{elapsed} minutes (since {no_worker_since.isoformat()}; "
                    f"alert threshold: {_fmt(config.no_worker_minutes)} minutes)."
                    f"{FOOTER}"
                ),
            )
        )

    if config.failure_rate > 0:
        counts = store.counts_since((now - FAILURE_WINDOW).isoformat())
        failed = counts["failed"]
        finished = counts["completed"] + failed
        if finished >= MIN_FINISHED_FOR_FAILURE_RATE and failed / finished >= config.failure_rate:
            alerts.append(
                Alert(
                    key="failure_rate",
                    subject=f"{SUBJECT_PREFIX} High job failure rate: {failed / finished:.0%}",
                    body=(
                        f"{failed} of {finished} jobs that finished in the last hour failed "
                        f"({failed / finished:.0%}; alert threshold: "
                        f"{config.failure_rate:.0%}). Cancelled jobs are not counted."
                        f"{FOOTER}"
                    ),
                )
            )

    return alerts


class AlertLoop:
    """Background checker that emails active admins; dedupe state is in memory."""

    def __init__(self, *, store, workers, recipients, config, send=None):
        self._store = store
        self._workers = workers
        self._recipients = recipients
        self._config = config
        self._send = send or email_sender.send_admin_alert
        self._last_sent: dict[str, datetime] = {}
        self._no_worker_since = None
        self._stop = threading.Event()
        self._thread = None

    def run_once(self, now=None):
        now = now or datetime.now(UTC)
        self._no_worker_since = next_no_worker_since(
            store=self._store,
            workers=self._workers,
            now=now,
            config=self._config,
            previous=self._no_worker_since,
        )
        alerts = evaluate_alerts(
            store=self._store,
            workers=self._workers,
            now=now,
            config=self._config,
            no_worker_since=self._no_worker_since,
        )
        active = {alert.key for alert in alerts}
        for key in list(self._last_sent):
            if key not in active:
                del self._last_sent[key]
        due = [
            alert
            for alert in alerts
            if alert.key not in self._last_sent
            or now - self._last_sent[alert.key] >= RESEND_INTERVAL
        ]
        if not due:
            return
        recipients = list(self._recipients())
        if not recipients:
            log.warning(
                "Admin alerts %s triggered but there are no active admins to email",
                [alert.key for alert in due],
            )
            return
        for alert in due:
            delivered = False
            for to in recipients:
                try:
                    self._send(to, alert.subject, alert.body)
                    delivered = True
                except Exception:  # noqa: BLE001 - a failed email must not stop other alerts.
                    log.exception("Failed to email admin alert %r to %s", alert.key, to)
            if delivered:
                self._last_sent[alert.key] = now

    def _run(self):
        while not self._stop.wait(self._config.check_seconds):
            try:
                self.run_once()
            except Exception:  # noqa: BLE001 - keep alerting alive across transient failures.
                log.exception("Admin alert check failed")

    def start(self):
        if self.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="admin-alerts", daemon=True)
        self._thread.start()

    def stop(self, timeout=None):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)

    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()
