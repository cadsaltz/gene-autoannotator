import pytest

GENEROUS_RATE_LIMITS = {
    "IP_SIGNUPS_PER_DAY": "100000",
    "OTP_SENDS_PER_EMAIL_PER_HOUR": "100000",
    "IP_SUBMITS_PER_HOUR": "100000",
}


# Every TestClient shares the "testclient" IP, so production rate-limit
# defaults would trip suites that sign up several users.
@pytest.fixture(autouse=True)
def generous_rate_limits(monkeypatch):
    for name, value in GENEROUS_RATE_LIMITS.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("TRUST_FORWARDED_FOR", raising=False)
