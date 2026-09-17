import os


def resolve_backend_url() -> str:
    url = (os.getenv("BACKEND_URL") or "").rstrip("/")
    if not url:
        raise RuntimeError("BACKEND_URL is required")
    return url
