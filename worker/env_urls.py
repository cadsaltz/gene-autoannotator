import os


def resolve_backend_url() -> str:
    url = (os.getenv("BACKEND_URL") or os.getenv("COORDINATOR_URL") or "").rstrip("/")
    if not url:
        raise RuntimeError("BACKEND_URL (or legacy COORDINATOR_URL) is required")
    return url
