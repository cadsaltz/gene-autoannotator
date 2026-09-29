import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from backend.access import BOOTSTRAP_ADMIN_EMAIL
from backend.rate_limits import RateLimiter, rate_limit_from_env
from tests.auth_helpers import make_client, second_client, sign_in, signed_in_client

JOB = {"profile": "mtb-h37rv", "locus": "Rv0001"}
BATCH = {
    "profile": "mtb-h37rv",
    "entries": [{"input": "Rv0001"}, {"input": "Rv0002"}],
    "allow_online_name_lookup": False,
}


@pytest.fixture(autouse=True)
def isolate_env(tmp_path, monkeypatch):
    monkeypatch.setenv("PROFILES_DIR", str(tmp_path / "profiles"))
    monkeypatch.delenv("MONGO_URI", raising=False)
    monkeypatch.delenv("MONGODB_URI", raising=False)


def test_limiter_allows_up_to_limit(tmp_path):
    limiter = RateLimiter(tmp_path / "db.sqlite3")
    assert limiter.hit("signup", "1.2.3.4", 86400, 2)
    assert limiter.hit("signup", "1.2.3.4", 86400, 2)
    assert not limiter.hit("signup", "1.2.3.4", 86400, 2)
    assert limiter.hit("signup", "5.6.7.8", 86400, 2)


def test_limiter_buckets_are_independent(tmp_path):
    limiter = RateLimiter(tmp_path / "db.sqlite3")
    assert limiter.hit("signup", "1.2.3.4", 86400, 1)
    assert limiter.hit("submit", "1.2.3.4", 86400, 1)
    assert not limiter.hit("signup", "1.2.3.4", 86400, 1)


def test_limiter_ignores_hits_outside_window_and_prunes_old_rows(tmp_path):
    db = tmp_path / "db.sqlite3"
    limiter = RateLimiter(db)
    old = (datetime.now(UTC) - timedelta(days=3)).isoformat()
    recent = (datetime.now(UTC) - timedelta(minutes=90)).isoformat()
    with sqlite3.connect(db) as connection:
        connection.executemany(
            "INSERT INTO rate_events (bucket, key, created_at) VALUES (?, ?, ?)",
            [("otp_send", "a@example.com", old), ("otp_send", "a@example.com", recent)],
        )
    assert limiter.hit("otp_send", "a@example.com", 3600, 1)
    with sqlite3.connect(db) as connection:
        rows = connection.execute(
            "SELECT created_at FROM rate_events WHERE bucket = 'otp_send'"
        ).fetchall()
    assert old not in {row[0] for row in rows}
    assert len(rows) == 2


def test_rate_limit_env_parsing(monkeypatch):
    monkeypatch.setenv("IP_SIGNUPS_PER_DAY", "3")
    assert rate_limit_from_env("IP_SIGNUPS_PER_DAY") == 3
    monkeypatch.setenv("IP_SIGNUPS_PER_DAY", "many")
    assert rate_limit_from_env("IP_SIGNUPS_PER_DAY") == 5
    monkeypatch.delenv("IP_SUBMITS_PER_HOUR", raising=False)
    monkeypatch.delenv("OTP_SENDS_PER_EMAIL_PER_HOUR", raising=False)
    assert rate_limit_from_env("IP_SUBMITS_PER_HOUR") == 30
    assert rate_limit_from_env("OTP_SENDS_PER_EMAIL_PER_HOUR") == 5


def test_signup_ip_limit(tmp_path, monkeypatch):
    monkeypatch.setenv("IP_SIGNUPS_PER_DAY", "1")
    client = make_client(tmp_path)
    assert client.post("/auth/signup", json={"email": "a@example.com"}).status_code == 200
    resp = client.post("/auth/signup", json={"email": "b@example.com"})
    assert resp.status_code == 429
    assert resp.json()["code"] == "rate_limited"
    assert resp.json()["detail"]


def test_zero_signup_limit_means_unlimited(tmp_path, monkeypatch):
    monkeypatch.setenv("IP_SIGNUPS_PER_DAY", "0")
    client = make_client(tmp_path)
    for index in range(3):
        resp = client.post("/auth/signup", json={"email": f"u{index}@example.com"})
        assert resp.status_code == 200


def test_signup_limit_uses_forwarded_ip_when_trusted(tmp_path, monkeypatch):
    monkeypatch.setenv("IP_SIGNUPS_PER_DAY", "1")
    monkeypatch.setenv("TRUST_FORWARDED_FOR", "1")
    client = make_client(tmp_path)
    first = {"x-forwarded-for": "9.9.9.9"}
    other = {"x-forwarded-for": "8.8.8.8, 9.9.9.9"}
    assert client.post("/auth/signup", json={"email": "a@example.com"}, headers=first).status_code == 200
    assert client.post("/auth/signup", json={"email": "b@example.com"}, headers=first).status_code == 429
    assert client.post("/auth/signup", json={"email": "c@example.com"}, headers=other).status_code == 200


def test_otp_send_limit_per_email(tmp_path, monkeypatch):
    monkeypatch.setenv("OTP_SENDS_PER_EMAIL_PER_HOUR", "1")
    client = make_client(tmp_path)
    client.post("/auth/signup", json={"email": "a@example.com"})
    resp = client.post("/auth/login", json={"email": "a@example.com"})
    assert resp.status_code == 429
    assert resp.json()["code"] == "rate_limited"
    assert client.post("/auth/login", json={"email": "b@example.com"}).status_code == 200


def test_otp_send_limit_ignores_email_case(tmp_path, monkeypatch):
    monkeypatch.setenv("OTP_SENDS_PER_EMAIL_PER_HOUR", "1")
    client = make_client(tmp_path)
    client.post("/auth/signup", json={"email": "a@example.com"})
    assert client.post("/auth/login", json={"email": "A@Example.com"}).status_code == 429


def test_login_for_unknown_email_counts_toward_otp_limit(tmp_path, monkeypatch):
    monkeypatch.setenv("OTP_SENDS_PER_EMAIL_PER_HOUR", "1")
    client = make_client(tmp_path)
    assert client.post("/auth/login", json={"email": "ghost@example.com"}).status_code == 200
    assert client.post("/auth/login", json={"email": "ghost@example.com"}).status_code == 429


def test_session_records_forwarded_ip_when_trusted(tmp_path, monkeypatch):
    monkeypatch.setenv("TRUST_FORWARDED_FOR", "1")
    client = make_client(tmp_path)
    client.headers["x-forwarded-for"] = "9.9.9.9, 10.0.0.1"
    sign_in(client, "a@example.com")
    with sqlite3.connect(client.auth_store.db_path) as connection:
        ips = [row[0] for row in connection.execute("SELECT ip FROM sessions")]
    assert ips == ["9.9.9.9"]


def test_session_ignores_forwarded_ip_when_untrusted(tmp_path):
    client = make_client(tmp_path)
    client.headers["x-forwarded-for"] = "9.9.9.9"
    sign_in(client, "a@example.com")
    with sqlite3.connect(client.auth_store.db_path) as connection:
        ips = [row[0] for row in connection.execute("SELECT ip FROM sessions")]
    assert ips == ["testclient"]


def test_submit_limit_per_ip_counts_jobs_and_batches(tmp_path, monkeypatch):
    monkeypatch.setenv("IP_SUBMITS_PER_HOUR", "2")
    alice = signed_in_client(tmp_path, email="alice@example.com")
    bob = second_client(alice, email="bob@example.com")
    assert alice.post("/jobs", json=JOB).status_code == 201
    assert alice.post("/batches", json=BATCH).status_code == 201
    resp = bob.post("/jobs", json=JOB)
    assert resp.status_code == 429
    assert resp.json()["code"] == "rate_limited"
    assert bob.post("/batches", json=BATCH).json()["code"] == "rate_limited"
    assert alice.get("/jobs/queue-status").json()["queued"] == 3


def test_rejected_submission_does_not_consume_submit_limit(tmp_path, monkeypatch):
    monkeypatch.setenv("IP_SUBMITS_PER_HOUR", "1")
    monkeypatch.setenv("USER_MAX_BATCH_SIZE", "1")
    alice = signed_in_client(tmp_path, email="alice@example.com")
    assert alice.post("/batches", json=BATCH).json()["code"] == "batch_limit"
    assert alice.post("/jobs", json=JOB).status_code == 201


def test_admin_is_exempt_from_submit_limit(tmp_path, monkeypatch):
    monkeypatch.setenv("IP_SUBMITS_PER_HOUR", "1")
    admin = signed_in_client(tmp_path, email=BOOTSTRAP_ADMIN_EMAIL)
    for _ in range(3):
        assert admin.post("/jobs", json=JOB).status_code == 201
    assert admin.post("/batches", json=BATCH).status_code == 201


def test_injected_rate_limiter_is_used(tmp_path, monkeypatch):
    class DenyAll:
        def hit(self, bucket, key, window_seconds, limit):
            return False

    client = make_client(tmp_path, rate_limiter=DenyAll())
    assert client.post("/auth/signup", json={"email": "a@example.com"}).status_code == 429


def test_forwarded_for_ignored_unless_trusted(tmp_path, monkeypatch):
    from backend.client_ip import client_ip

    class Req:
        headers = {"x-forwarded-for": "9.9.9.9, 10.0.0.1"}
        class client:
            host = "10.0.0.5"

    monkeypatch.delenv("TRUST_FORWARDED_FOR", raising=False)
    assert client_ip(Req) == "10.0.0.5"
    monkeypatch.setenv("TRUST_FORWARDED_FOR", "1")
    assert client_ip(Req) == "9.9.9.9"


@pytest.mark.parametrize("flag", ["true", "YES", " 1 "])
def test_trust_forwarded_for_accepts_boolean_spellings(monkeypatch, flag):
    from backend.client_ip import client_ip

    class Req:
        headers = {"x-forwarded-for": "9.9.9.9"}
        client = None

    monkeypatch.setenv("TRUST_FORWARDED_FOR", flag)
    assert client_ip(Req) == "9.9.9.9"


def test_trusted_but_missing_forwarded_for_falls_back_to_socket(monkeypatch):
    from backend.client_ip import client_ip

    class Req:
        headers = {"x-forwarded-for": " , 10.0.0.1"}
        class client:
            host = "10.0.0.5"

    class NoClient:
        headers = {}
        client = None

    monkeypatch.setenv("TRUST_FORWARDED_FOR", "1")
    assert client_ip(Req) == "10.0.0.5"
    monkeypatch.setenv("TRUST_FORWARDED_FOR", "0")
    assert client_ip(NoClient) is None
