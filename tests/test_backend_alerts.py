import logging
import threading
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from backend import email_sender
from backend.access import BOOTSTRAP_ADMIN_EMAIL
from backend.alerts import (
    RESEND_INTERVAL,
    Alert,
    AlertConfig,
    AlertLoop,
    evaluate_alerts,
    next_no_worker_since,
)
from backend.auth_store import AuthStore
from tests.auth_helpers import make_client

NOW = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)


class FakeStore:
    def __init__(self, *, queued=0, completed=0, failed=0, cancelled=0):
        self.queued = queued
        self.completed = completed
        self.failed = failed
        self.cancelled = cancelled
        self.since_calls = []

    def count_queued_jobs(self):
        return self.queued

    def counts_since(self, since_iso):
        self.since_calls.append(since_iso)
        return {"completed": self.completed, "failed": self.failed, "cancelled": self.cancelled}


class FakeWorkers:
    """`connected` counts ready workers; draining ones are online but take no jobs."""

    def __init__(self, connected=1, *, provisioning=0, draining=0):
        self.connected = connected
        self.provisioning = provisioning
        self.draining = draining
        self.offline_after = []

    def summary(self, *, offline_after_seconds=60):
        self.offline_after.append(offline_after_seconds)
        online = self.connected + self.provisioning + self.draining
        return {
            "connected": online,
            "total": online,
            "used_slots": 0,
            "available_slots": self.connected + self.provisioning,
            "total_slots": online,
            "states": {
                "ready": self.connected,
                "provisioning": self.provisioning,
                "draining": self.draining,
                "offline": 0,
            },
        }


def config(**overrides):
    values = {
        "check_seconds": 300,
        "queue_depth": 50,
        "no_worker_minutes": 15,
        "failure_rate": 0.5,
        "offline_after_seconds": 60,
    }
    values.update(overrides)
    return AlertConfig(**values)


def keys(alerts):
    return {alert.key for alert in alerts}


# --- queue depth -----------------------------------------------------------


def test_queue_depth_alert_fires_at_threshold():
    alerts = evaluate_alerts(
        store=FakeStore(queued=50), workers=FakeWorkers(), now=NOW, config=config()
    )
    assert keys(alerts) == {"queue_depth"}
    alert = alerts[0]
    assert isinstance(alert, Alert)
    assert "50" in alert.subject + alert.body


def test_queue_depth_alert_quiet_below_threshold():
    alerts = evaluate_alerts(
        store=FakeStore(queued=49), workers=FakeWorkers(), now=NOW, config=config()
    )
    assert alerts == []


def test_queue_depth_rule_disabled_by_zero():
    alerts = evaluate_alerts(
        store=FakeStore(queued=10_000),
        workers=FakeWorkers(),
        now=NOW,
        config=config(queue_depth=0),
    )
    assert "queue_depth" not in keys(alerts)


# --- no online worker ------------------------------------------------------


def test_no_worker_alert_fires_after_threshold_minutes():
    alerts = evaluate_alerts(
        store=FakeStore(queued=3),
        workers=FakeWorkers(connected=0),
        now=NOW,
        config=config(),
        no_worker_since=NOW - timedelta(minutes=15),
    )
    assert keys(alerts) == {"no_worker"}
    assert "3" in alerts[0].body
    assert "15" in alerts[0].body


def test_no_worker_alert_quiet_before_threshold():
    alerts = evaluate_alerts(
        store=FakeStore(queued=3),
        workers=FakeWorkers(connected=0),
        now=NOW,
        config=config(),
        no_worker_since=NOW - timedelta(minutes=14, seconds=59),
    )
    assert alerts == []


def test_no_worker_alert_needs_tracked_start():
    alerts = evaluate_alerts(
        store=FakeStore(queued=3),
        workers=FakeWorkers(connected=0),
        now=NOW,
        config=config(),
        no_worker_since=None,
    )
    assert alerts == []


@pytest.mark.parametrize("queued,connected", [(0, 0), (3, 1)])
def test_no_worker_alert_needs_queued_jobs_and_no_workers(queued, connected):
    alerts = evaluate_alerts(
        store=FakeStore(queued=queued),
        workers=FakeWorkers(connected=connected),
        now=NOW,
        config=config(),
        no_worker_since=NOW - timedelta(hours=2),
    )
    assert "no_worker" not in keys(alerts)


def test_no_worker_rule_disabled_by_zero():
    alerts = evaluate_alerts(
        store=FakeStore(queued=3),
        workers=FakeWorkers(connected=0),
        now=NOW,
        config=config(no_worker_minutes=0),
        no_worker_since=NOW - timedelta(hours=2),
    )
    assert alerts == []


def test_no_worker_alert_fires_when_only_draining_workers_remain():
    store, workers = FakeStore(queued=3), FakeWorkers(connected=0, draining=2)
    since = next_no_worker_since(
        store=store, workers=workers, now=NOW - timedelta(minutes=15), config=config(), previous=None
    )
    assert since == NOW - timedelta(minutes=15)
    alerts = evaluate_alerts(
        store=store, workers=workers, now=NOW, config=config(), no_worker_since=since
    )
    assert keys(alerts) == {"no_worker"}


def test_provisioning_worker_counts_as_job_taking():
    assert (
        next_no_worker_since(
            store=FakeStore(queued=3),
            workers=FakeWorkers(connected=0, provisioning=1),
            now=NOW,
            config=config(),
            previous=None,
        )
        is None
    )


def test_evaluate_uses_configured_offline_window():
    workers = FakeWorkers()
    evaluate_alerts(
        store=FakeStore(), workers=workers, now=NOW, config=config(offline_after_seconds=90)
    )
    assert workers.offline_after and set(workers.offline_after) == {90}


def test_next_no_worker_since_tracks_condition_start():
    store, workers = FakeStore(queued=2), FakeWorkers(connected=0)
    started = next_no_worker_since(
        store=store, workers=workers, now=NOW, config=config(), previous=None
    )
    assert started == NOW

    later = NOW + timedelta(minutes=5)
    assert (
        next_no_worker_since(
            store=store, workers=workers, now=later, config=config(), previous=started
        )
        == started
    )

    workers.connected = 1
    assert (
        next_no_worker_since(
            store=store, workers=workers, now=later, config=config(), previous=started
        )
        is None
    )


def test_next_no_worker_since_ignores_idle_empty_queue():
    assert (
        next_no_worker_since(
            store=FakeStore(queued=0),
            workers=FakeWorkers(connected=0),
            now=NOW,
            config=config(),
            previous=NOW - timedelta(hours=1),
        )
        is None
    )


# --- failure rate ----------------------------------------------------------


def test_failure_rate_alert_fires_with_enough_finished_jobs():
    store = FakeStore(completed=2, failed=3)
    alerts = evaluate_alerts(store=store, workers=FakeWorkers(), now=NOW, config=config())
    assert keys(alerts) == {"failure_rate"}
    assert "3" in alerts[0].body and "5" in alerts[0].body
    assert store.since_calls == [(NOW - timedelta(hours=1)).isoformat()]


def test_failure_rate_alert_needs_five_finished_jobs():
    alerts = evaluate_alerts(
        store=FakeStore(completed=0, failed=4),
        workers=FakeWorkers(),
        now=NOW,
        config=config(),
    )
    assert alerts == []


def test_failure_rate_alert_quiet_below_threshold():
    alerts = evaluate_alerts(
        store=FakeStore(completed=3, failed=2),
        workers=FakeWorkers(),
        now=NOW,
        config=config(),
    )
    assert alerts == []


def test_failure_rate_ignores_cancelled_jobs():
    alerts = evaluate_alerts(
        store=FakeStore(completed=1, failed=3, cancelled=20),
        workers=FakeWorkers(),
        now=NOW,
        config=config(),
    )
    assert alerts == []


def test_failure_rate_rule_disabled_by_zero():
    alerts = evaluate_alerts(
        store=FakeStore(completed=0, failed=50),
        workers=FakeWorkers(),
        now=NOW,
        config=config(failure_rate=0),
    )
    assert alerts == []


def test_alert_text_never_contains_secrets(monkeypatch):
    monkeypatch.setenv("WORKER_API_TOKEN", "super-secret-worker-token")
    monkeypatch.setenv("RESEND_API_KEY", "re_secret_key_value")
    alerts = evaluate_alerts(
        store=FakeStore(queued=500, completed=0, failed=10),
        workers=FakeWorkers(connected=0),
        now=NOW,
        config=config(),
        no_worker_since=NOW - timedelta(hours=1),
    )
    assert keys(alerts) == {"queue_depth", "no_worker", "failure_rate"}
    for alert in alerts:
        text = alert.subject + alert.body
        assert "super-secret-worker-token" not in text
        assert "re_secret_key_value" not in text


# --- config parsing --------------------------------------------------------


ALERT_ENV = (
    "ALERT_CHECK_SECONDS",
    "ALERT_QUEUE_DEPTH",
    "ALERT_NO_WORKER_MINUTES",
    "ALERT_FAILURE_RATE",
)


def test_config_defaults(monkeypatch):
    for name in ALERT_ENV:
        monkeypatch.delenv(name, raising=False)
    cfg = AlertConfig.from_env(offline_after_seconds=45)
    assert cfg == AlertConfig(
        check_seconds=300,
        queue_depth=50,
        no_worker_minutes=15,
        failure_rate=0.5,
        offline_after_seconds=45,
    )
    assert cfg.enabled


def test_config_bad_values_fall_back_to_defaults(monkeypatch, caplog):
    monkeypatch.setenv("ALERT_CHECK_SECONDS", "soon")
    monkeypatch.setenv("ALERT_QUEUE_DEPTH", "lots")
    monkeypatch.setenv("ALERT_NO_WORKER_MINUTES", "")
    monkeypatch.setenv("ALERT_FAILURE_RATE", "nan")
    with caplog.at_level(logging.WARNING, logger="backend.alerts"):
        cfg = AlertConfig.from_env()
    assert (cfg.check_seconds, cfg.queue_depth, cfg.no_worker_minutes, cfg.failure_rate) == (
        300,
        50,
        15,
        0.5,
    )
    warned = caplog.text
    for name in ALERT_ENV:
        assert name in warned


def test_config_clamps_check_interval_to_one_day(monkeypatch):
    monkeypatch.setenv("ALERT_CHECK_SECONDS", "1e12")
    assert AlertConfig.from_env().check_seconds == 86400


def test_config_accepts_float_strings_for_int_settings(monkeypatch):
    monkeypatch.setenv("ALERT_QUEUE_DEPTH", "40.0")
    cfg = AlertConfig.from_env()
    assert cfg.queue_depth == 40 and isinstance(cfg.queue_depth, int)


def test_config_zero_disables(monkeypatch):
    monkeypatch.setenv("ALERT_CHECK_SECONDS", "0")
    monkeypatch.setenv("ALERT_QUEUE_DEPTH", "-1")
    monkeypatch.setenv("ALERT_NO_WORKER_MINUTES", "0")
    monkeypatch.setenv("ALERT_FAILURE_RATE", "0.25")
    cfg = AlertConfig.from_env()
    assert not cfg.enabled
    assert cfg.queue_depth == -1
    assert cfg.no_worker_minutes == 0
    assert cfg.failure_rate == 0.25


# --- AlertLoop dedupe and delivery ----------------------------------------


class Outbox:
    def __init__(self, fail_for=()):
        self.sent = []
        self.fail_for = set(fail_for)

    def __call__(self, to, subject, body):
        if to in self.fail_for:
            raise RuntimeError("smtp down")
        self.sent.append((to, subject, body))


def make_loop(store, workers, outbox, admins=("a@example.com", "b@example.com"), **cfg):
    return AlertLoop(
        store=store,
        workers=workers,
        recipients=lambda: list(admins),
        config=config(**cfg),
        send=outbox,
    )


def test_loop_emails_every_active_admin():
    outbox = Outbox()
    loop = make_loop(FakeStore(queued=60), FakeWorkers(), outbox)
    loop.run_once(now=NOW)
    assert sorted(to for to, _, _ in outbox.sent) == ["a@example.com", "b@example.com"]


def test_loop_resends_same_key_at_most_every_six_hours():
    assert RESEND_INTERVAL == timedelta(hours=6)
    outbox = Outbox()
    loop = make_loop(FakeStore(queued=60), FakeWorkers(), outbox, admins=("a@example.com",))

    loop.run_once(now=NOW)
    loop.run_once(now=NOW + timedelta(minutes=5))
    loop.run_once(now=NOW + timedelta(hours=5, minutes=59))
    assert len(outbox.sent) == 1

    loop.run_once(now=NOW + timedelta(hours=6))
    assert len(outbox.sent) == 2


def test_loop_dedupes_per_key():
    outbox = Outbox()
    store = FakeStore(queued=60)
    loop = make_loop(store, FakeWorkers(), outbox, admins=("a@example.com",))
    loop.run_once(now=NOW)

    store.completed, store.failed = 0, 5
    loop.run_once(now=NOW + timedelta(minutes=5))
    subjects = [subject for _, subject, _ in outbox.sent]
    assert len(subjects) == 2 and subjects[0] != subjects[1]


def test_loop_realerts_new_incident_after_condition_resolves():
    outbox = Outbox()
    store = FakeStore(queued=60)
    loop = make_loop(store, FakeWorkers(), outbox, admins=("a@example.com",))
    loop.run_once(now=NOW)

    store.queued = 0
    loop.run_once(now=NOW + timedelta(minutes=5))

    store.queued = 60
    loop.run_once(now=NOW + timedelta(minutes=10))
    assert len(outbox.sent) == 2


def test_loop_tracks_no_worker_start_across_runs():
    outbox = Outbox()
    loop = make_loop(
        FakeStore(queued=2), FakeWorkers(connected=0), outbox, admins=("a@example.com",)
    )
    loop.run_once(now=NOW)
    assert outbox.sent == []
    loop.run_once(now=NOW + timedelta(minutes=15))
    assert len(outbox.sent) == 1


def test_loop_email_failure_does_not_raise_and_other_admins_still_get_it():
    outbox = Outbox(fail_for={"a@example.com"})
    loop = make_loop(FakeStore(queued=60), FakeWorkers(), outbox)
    loop.run_once(now=NOW)
    assert [to for to, _, _ in outbox.sent] == ["b@example.com"]


def test_loop_retries_alert_when_no_admin_received_it():
    outbox = Outbox(fail_for={"a@example.com"})
    loop = make_loop(FakeStore(queued=60), FakeWorkers(), outbox, admins=("a@example.com",))
    loop.run_once(now=NOW)
    outbox.fail_for.clear()
    loop.run_once(now=NOW + timedelta(minutes=5))
    assert len(outbox.sent) == 1


def test_loop_thread_survives_errors_and_stops_cleanly():
    delivered = threading.Event()

    class FlakyStore(FakeStore):
        calls = 0

        def count_queued_jobs(self):
            FlakyStore.calls += 1
            if FlakyStore.calls == 1:
                raise RuntimeError("database is locked")
            return self.queued

    def send(to, subject, body):
        delivered.set()

    loop = AlertLoop(
        store=FlakyStore(queued=60),
        workers=FakeWorkers(),
        recipients=lambda: ["a@example.com"],
        config=config(check_seconds=0.01),
        send=send,
    )
    loop.start()
    try:
        assert delivered.wait(5)
    finally:
        loop.stop(timeout=5)
    assert not loop.is_alive()


def test_loop_start_twice_keeps_one_thread():
    loop = make_loop(FakeStore(), FakeWorkers(), Outbox(), check_seconds=60)
    loop.start()
    try:
        first = loop._thread
        loop.start()
        assert loop._thread is first
    finally:
        loop.stop(timeout=5)
    assert not loop.is_alive()


def test_job_store_indexes_finished_at(tmp_path):
    import sqlite3

    from backend.job_store import JobStore

    store = JobStore(tmp_path / "jobs.sqlite3")
    with sqlite3.connect(store.db_path) as connection:
        columns = [
            row[2]
            for row in connection.execute("PRAGMA index_info(idx_jobs_finished)").fetchall()
        ]
    assert columns == ["finished_at", "status"]


# --- email transport and admin lookup --------------------------------------


def test_send_admin_alert_console_records_and_logs(monkeypatch, caplog):
    monkeypatch.setenv("EMAIL_BACKEND", "console")
    email_sender._CONSOLE_OUTBOX.clear()
    with caplog.at_level(logging.INFO, logger="backend.email_sender"):
        email_sender.send_admin_alert("admin@example.com", "Queue is deep", "60 queued")
    assert email_sender._CONSOLE_OUTBOX[-1] == {
        "to": "admin@example.com",
        "subject": "Queue is deep",
        "body": "60 queued",
    }
    assert "Queue is deep" in caplog.text


def test_list_active_admin_emails(tmp_path):
    auth = AuthStore(tmp_path / "jobs.sqlite3")
    auth.create_user(email=BOOTSTRAP_ADMIN_EMAIL, username=None)
    promoted = auth.create_user(email="second@example.com", username=None)
    auth.set_role(promoted["id"], "admin")
    suspended = auth.create_user(email="gone@example.com", username=None)
    auth.set_role(suspended["id"], "admin")
    auth.set_status(suspended["id"], "suspended")
    auth.create_user(email="user@example.com", username=None)

    assert sorted(auth.list_active_admin_emails()) == sorted(
        [BOOTSTRAP_ADMIN_EMAIL, "second@example.com"]
    )


# --- app lifespan ----------------------------------------------------------


def test_app_does_not_start_alert_loop_when_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv("ALERT_CHECK_SECONDS", "0")
    client = make_client(tmp_path)
    with TestClient(client.app):
        assert client.app.state.alert_loop is None


def test_app_lifespan_starts_and_stops_alert_loop(tmp_path, monkeypatch):
    monkeypatch.setenv("ALERT_CHECK_SECONDS", "0.05")
    client = make_client(tmp_path)
    with TestClient(client.app):
        loop = client.app.state.alert_loop
        assert loop is not None and loop.is_alive()
    assert not loop.is_alive()
