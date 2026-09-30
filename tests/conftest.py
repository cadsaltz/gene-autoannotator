import pytest

GENEROUS_RATE_LIMITS = {
    "IP_SIGNUPS_PER_DAY": "100000",
    "IP_LOGINS_PER_HOUR": "100000",
    "OTP_SENDS_PER_EMAIL_PER_HOUR": "100000",
    "IP_SUBMITS_PER_HOUR": "100000",
    "IP_VALIDATIONS_PER_HOUR": "100000",
}


# Every TestClient shares the "testclient" IP, so production rate-limit
# defaults would trip suites that sign up several users.
@pytest.fixture(autouse=True)
def generous_rate_limits(monkeypatch):
    for name, value in GENEROUS_RATE_LIMITS.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("TRUST_FORWARDED_FOR", raising=False)


# App lifespans would otherwise start alert, backup, and retention threads that
# outlive the test (a developer .env may set MONGO_URI).
@pytest.fixture(autouse=True)
def background_loops_disabled(monkeypatch):
    monkeypatch.setenv("ALERT_CHECK_SECONDS", "0")
    monkeypatch.setenv("BACKUP_INTERVAL_SECONDS", "0")
    monkeypatch.setenv("JOB_RETENTION_DAYS", "0")
