"""Pinned Ollama *server* version for this project.

The Python package in ``requirements.txt`` (``ollama==…``) is only the HTTP
client. The server binary/image version is controlled here and in
``deploy/docker/Dockerfile.worker``.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request

log = logging.getLogger(__name__)

# Project-wide Ollama server pin. Bump only when deliberately upgrading.
PINNED_OLLAMA_SERVER_VERSION = "0.24.0"


def required_ollama_server_version() -> str | None:
    """Return the required server version, or None to skip enforcement.

    Override with ``OLLAMA_REQUIRE_VERSION`` (empty / ``off`` / ``0`` disables).
    """
    raw = os.getenv("OLLAMA_REQUIRE_VERSION")
    if raw is None:
        return PINNED_OLLAMA_SERVER_VERSION
    value = raw.strip()
    if value.lower() in {"", "0", "off", "false", "no", "any", "*"}:
        return None
    return value


def fetch_ollama_server_version(host: str, *, timeout_sec: float = 5.0) -> str:
    """GET ``/api/version`` from an Ollama base URL (e.g. http://127.0.0.1:11434)."""
    base = host.rstrip("/")
    if not base.startswith("http"):
        base = f"http://{base}"
    url = f"{base}/api/version"
    request = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(request, timeout=timeout_sec) as response:
        payload = json.loads(response.read().decode("utf-8"))
    version = payload.get("version")
    if not version:
        raise RuntimeError(f"Ollama /api/version missing version field: {payload!r}")
    return str(version).strip()


def _version_matches(actual: str, required: str) -> bool:
    """True if actual equals required, or actual is required with a suffix (0.24.0-rc1)."""
    actual_n = actual.strip().lstrip("v")
    required_n = required.strip().lstrip("v")
    if actual_n == required_n:
        return True
    # Allow patch-equivalent tags like 0.24.0+… only when the required string is a prefix
    # of the numeric version before build metadata.
    actual_core = actual_n.split("+", 1)[0]
    return actual_core == required_n or actual_core.startswith(required_n + ".")


def assert_ollama_server_version(host: str) -> str | None:
    """Ensure the running server matches the project pin.

    Returns the observed version when checked. Raises ``RuntimeError`` on mismatch
    when enforcement is enabled.
    """
    required = required_ollama_server_version()
    if required is None:
        return None
    try:
        actual = fetch_ollama_server_version(host)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, RuntimeError) as exc:
        raise RuntimeError(
            f"Could not read Ollama version from {host}: {exc}. "
            f"This project pins Ollama server {required}."
        ) from exc
    if not _version_matches(actual, required):
        raise RuntimeError(
            f"Ollama server version is {actual!r}, but this project requires "
            f"{required!r} (set OLLAMA_REQUIRE_VERSION=off to bypass). "
            f"Rebuild the worker image from deploy/docker/Dockerfile.worker "
            f"(FROM ollama/ollama:{required}) or install Ollama {required} on the host."
        )
    log.info("Ollama server version ok: %s (required %s)", actual, required)
    return actual
