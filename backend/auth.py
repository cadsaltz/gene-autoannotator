import hashlib
import secrets

SESSION_COOKIE_NAME = "ga_session"
OTP_TTL_SECONDS = 10 * 60
OTP_MAX_ATTEMPTS = 5
SESSION_TTL_SECONDS = 90 * 24 * 60 * 60


def hash_secret(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def new_otp_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"
