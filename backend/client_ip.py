import os

TRUE_VALUES = {"1", "true", "yes", "on"}


def _trust_forwarded_for() -> bool:
    return (os.getenv("TRUST_FORWARDED_FOR") or "").strip().lower() in TRUE_VALUES


def client_ip(request) -> str | None:
    # Only trust X-Forwarded-For behind a proxy that overwrites it (Caddy does
    # by default); otherwise any client could pick its own rate-limit key.
    if _trust_forwarded_for():
        forwarded = request.headers.get("x-forwarded-for") or ""
        leftmost = forwarded.split(",")[0].strip()
        if leftmost:
            return leftmost
    client = request.client
    return client.host if client else None
