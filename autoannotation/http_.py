import logging
import os
import time

import cloudscraper as cs
import requests
from urllib3.exceptions import ProtocolError

from . import utils

COOLDOWN_SECONDS_DEFAULT = 0.5
TIMEOUT_SECONDS_DEFAULT = 60
GET_ATTEMPTS_DEFAULT = 3
GET_RETRY_BACKOFF_SECONDS_DEFAULT = 1.0

_RETRYABLE_REQUEST_ERRORS = (
    requests.exceptions.ChunkedEncodingError,
    requests.exceptions.ConnectionError,
    requests.exceptions.Timeout,
    ProtocolError,
)
_RETRYABLE_HTTP_STATUS = frozenset({429, 502, 503, 504})


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _get_attempts() -> int:
    return max(1, _int_env("AUTOANNOTATION_HTTP_GET_ATTEMPTS", GET_ATTEMPTS_DEFAULT))


def _get_retry_backoff_seconds() -> float:
    return max(0.0, _float_env(
        "AUTOANNOTATION_HTTP_RETRY_BACKOFF_SEC",
        GET_RETRY_BACKOFF_SECONDS_DEFAULT,
    ))


def _is_retryable_request_error(exc: BaseException) -> bool:
    if isinstance(exc, _RETRYABLE_REQUEST_ERRORS):
        return True
    response = getattr(exc, "response", None)
    if response is not None and getattr(response, "status_code", None) in _RETRYABLE_HTTP_STATUS:
        return True
    return False


def ncbi_api_key_param():
    key = os.getenv("NCBI_API_KEY") or os.getenv("ENTREZ_API_KEY")
    return f"&api_key={key}" if key else ""

logging.basicConfig(format='%(asctime)s %(levelname).1s | %(message)s')
log = logging.getLogger(__name__)
log.setLevel(logging.DEBUG)

# Shared request pacing for external literature/name services. The throttler is
# intentionally simple and per-process; it prevents bursts from one run but is
# not a distributed rate limiter.
class Throttler:
    def __init__(self, cooldown_secs=None, timeout_secs=None):
        self.cooldown_seconds = COOLDOWN_SECONDS_DEFAULT if cooldown_secs is None else cooldown_secs
        self.last_requests = {}
        self.scraper = cs.create_scraper()
        self.timeout = TIMEOUT_SECONDS_DEFAULT if timeout_secs is None else timeout_secs
        if self.cooldown_seconds <= 1:
            log.info(
                f'Using throttler to make no more than {1/self.cooldown_seconds:.0f} ' + \
                    f'request{utils.s_if_plural(self.cooldown_seconds)} per second'
            )
        else:
            log.info(
                f'Using throttler to make no more than one request per ' + \
                    f'{self.cooldown_seconds} seconds'
            )

    def get(self, url, base_url):
        return self.throttle(
            base_url,
            lambda: self.scraper.get(url, timeout=self.timeout),
        )

    def throttle(self, label, throttled_function):
        if label in self.last_requests:
            time_passed = time.time() - self.last_requests[label]
            if time_passed < self.cooldown_seconds:
                wait_time = self.cooldown_seconds - time_passed
                log.debug(f'Slowing down requests: sleeping for {wait_time:.3f}s')
                time.sleep(wait_time)

        attempts = _get_attempts()
        backoff = _get_retry_backoff_seconds()
        last_exc: BaseException | None = None
        for attempt in range(1, attempts + 1):
            try:
                return_value = throttled_function()
            except BaseException as exc:
                last_exc = exc
                if attempt >= attempts or not _is_retryable_request_error(exc):
                    raise
                sleep_for = backoff * (2 ** (attempt - 1))
                log.warning(
                    'Request to %s failed (%s); retrying in %.1fs (%s/%s)',
                    label,
                    exc,
                    sleep_for,
                    attempt,
                    attempts,
                )
                time.sleep(sleep_for)
                continue

            status_code = getattr(return_value, "status_code", None)
            if status_code in _RETRYABLE_HTTP_STATUS:
                last_exc = requests.exceptions.HTTPError(
                    f'{status_code} from {label}',
                    response=return_value,
                )
                if attempt >= attempts:
                    return_value.raise_for_status()
                sleep_for = backoff * (2 ** (attempt - 1))
                log.warning(
                    'Request to %s returned HTTP %s; retrying in %.1fs (%s/%s)',
                    label,
                    status_code,
                    sleep_for,
                    attempt,
                    attempts,
                )
                time.sleep(sleep_for)
                continue

            self.last_requests[label] = time.time()
            return return_value

        if last_exc is not None:
            raise last_exc
        raise RuntimeError(f'Request to {label} failed without response')
