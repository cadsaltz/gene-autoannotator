import logging
import os
import time

import httpx

from shared.redact import redact_url_secrets

log = logging.getLogger(__name__)

_TRANSIENT_ERRORS = (
    httpx.RemoteProtocolError,
    httpx.ConnectError,
    httpx.ReadError,
    httpx.WriteError,
    httpx.ConnectTimeout,
    httpx.ReadTimeout,
    httpx.PoolTimeout,
)

# Home/NAT paths drop idle keep-alives; retry a few times before failing the call.
_MAX_ATTEMPTS = 4
_RETRY_BACKOFF_SEC = (0.5, 1.0, 2.0)

# complete/fail must outlive a backend container swap so finished results are not lost.
DEFAULT_COMPLETE_RETRY_SECONDS = 300.0
_DEADLINE_BACKOFF_INITIAL_SEC = 0.5
_DEADLINE_BACKOFF_MAX_SEC = 30.0
# Proxy/gateway codes seen while the backend container is swapped; a 500 is an
# application error that retrying will not fix.
_RETRYABLE_STATUS = frozenset({502, 503, 504})


def _complete_retry_seconds():
    raw = os.getenv("WORKER_COMPLETE_RETRY_SECONDS", "").strip()
    if not raw:
        return DEFAULT_COMPLETE_RETRY_SECONDS
    try:
        return max(0.0, float(raw))
    except ValueError:
        log.warning(
            "Invalid WORKER_COMPLETE_RETRY_SECONDS=%r; using %.0fs",
            raw,
            DEFAULT_COMPLETE_RETRY_SECONDS,
        )
        return DEFAULT_COMPLETE_RETRY_SECONDS


class JobCancelled(Exception):
    def __init__(self, job_id):
        super().__init__(f"Job {job_id} was cancelled")
        self.job_id = job_id


def _is_cancelled_response(response):
    if response.status_code != 409:
        return False
    try:
        body = response.json()
    except ValueError:
        return False
    return isinstance(body, dict) and body.get("cancelled") is True


class BackendClient:
    def __init__(self, config, http_client=None):
        self._config = config
        self._http = http_client or httpx.Client(
            base_url=config.backend_url,
            timeout=60.0,
            # Prefer fresh connections over long-lived keep-alives that die on
            # residential NAT after a long annotation job.
            limits=httpx.Limits(max_keepalive_connections=5, keepalive_expiry=30.0),
        )
        self._auth = {"Authorization": f"Bearer {config.worker_api_token}"}
        self.worker_id = None

    def _request(self, method, path, *, deadline_seconds=None, **kwargs):
        if deadline_seconds is not None:
            return self._request_until_deadline(method, path, deadline_seconds, **kwargs)
        attempt = 0
        while True:
            attempt += 1
            try:
                return getattr(self._http, method)(path, **kwargs)
            except _TRANSIENT_ERRORS as exc:
                if attempt >= _MAX_ATTEMPTS:
                    raise
                delay = _RETRY_BACKOFF_SEC[min(attempt - 1, len(_RETRY_BACKOFF_SEC) - 1)]
                log.warning(
                    "Transient backend %s %s failed (%s); retrying in %.1fs (%d/%d)",
                    method.upper(),
                    path,
                    exc,
                    delay,
                    attempt,
                    _MAX_ATTEMPTS,
                )
                time.sleep(delay)

    def _request_until_deadline(self, method, path, deadline_seconds, **kwargs):
        """Retry transport errors and 502/503/504 with capped exponential backoff
        until `deadline_seconds` elapse. Any other response is returned at once."""
        deadline = time.monotonic() + deadline_seconds
        delay = _DEADLINE_BACKOFF_INITIAL_SEC
        attempt = 0
        while True:
            attempt += 1
            try:
                response = getattr(self._http, method)(path, **kwargs)
            except _TRANSIENT_ERRORS as exc:
                reason = str(exc)
                last_error = exc
                response = None
            else:
                if response.status_code not in _RETRYABLE_STATUS:
                    return response
                reason = f"HTTP {response.status_code}"
                last_error = None
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                if last_error is not None:
                    raise last_error
                return response
            wait = min(delay, remaining)
            log.warning(
                "Backend %s %s failed (%s); retrying in %.1fs (attempt %d, %.0fs left)",
                method.upper(),
                path,
                reason,
                wait,
                attempt,
                remaining,
            )
            time.sleep(wait)
            delay = min(delay * 2, _DEADLINE_BACKOFF_MAX_SEC)

    def register(self):
        response = self._request(
            "post",
            "/workers/register",
            headers=self._auth,
            json={
                "worker_name": self._config.worker_name,
                "hostname": self._config.hostname,
                "agent_version": self._config.agent_version,
                "total_memory_bytes": self._config.total_memory_bytes,
                "dedicated_memory_bytes": self._config.dedicated_memory_bytes,
                "max_slots": self._config.max_slots,
                "ollama_models": [],
            },
        )
        response.raise_for_status()
        self.worker_id = response.json()["worker_id"]
        return self.worker_id

    def deregister(self):
        if self.worker_id is None:
            return
        response = self._request("delete", f"/workers/{self.worker_id}", headers=self._auth)
        if response.status_code == 404:
            return
        response.raise_for_status()

    def heartbeat(self, active_jobs, free_slots, memory_available_bytes, cpu_percent, state):
        response = self._request(
            "post",
            f"/workers/{self.worker_id}/heartbeat",
            headers=self._auth,
            json={
                "active_jobs": active_jobs,
                "free_slots": free_slots,
                "memory_available_bytes": memory_available_bytes,
                "cpu_percent": cpu_percent,
                "state": state,
            },
        )
        response.raise_for_status()
        return response.json()

    def claim(self, free_slots):
        response = self._request(
            "post",
            f"/workers/{self.worker_id}/claim",
            headers=self._auth,
            json={"free_slots": free_slots},
        )
        if response.status_code == 204:
            return None
        response.raise_for_status()
        return response.json()

    def progress(self, job_id, current_step, **fields):
        payload = {"current_step": current_step}
        for key in (
            "phase",
            "sections_done",
            "sections_total",
            "papers_done",
            "papers_total",
            "pass_name",
        ):
            value = fields.get(key)
            if value is not None:
                payload[key] = value
        response = self._request(
            "patch", f"/jobs/{job_id}/progress", headers=self._auth, json=payload
        )
        if _is_cancelled_response(response):
            raise JobCancelled(job_id)
        response.raise_for_status()

    def _with_worker_id(self, payload):
        if self.worker_id is not None:
            payload["worker_id"] = self.worker_id
        return payload

    def complete(self, job_id, result):
        self._request(
            "post",
            f"/jobs/{job_id}/complete",
            headers=self._auth,
            json=self._with_worker_id({"result": result}),
            deadline_seconds=_complete_retry_seconds(),
        ).raise_for_status()

    def fail(self, job_id, error, retryable):
        self._request(
            "post",
            f"/jobs/{job_id}/fail",
            headers=self._auth,
            json=self._with_worker_id(
                {"error": redact_url_secrets(error), "retryable": retryable}
            ),
            deadline_seconds=_complete_retry_seconds(),
        ).raise_for_status()
