"""Debounced progress reporter that forwards `JobProgressEvent` updates to the
coordinator via `CoordinatorClient.progress(...)`.

Debounce policy
----------------
- The first event reported for a job is always sent immediately.
- Any event whose `phase` differs from the last *sent* phase for that job is
  always sent immediately — phase transitions are never delayed.
- Events with the same phase as the last sent event are coalesced: at most
  one send per `debounce_sec` window (default `1.5`, overridable via the
  `WORKER_PROGRESS_DEBOUNCE_SEC` env var). While inside the window, only the
  latest event is kept as "pending" and is sent once the window elapses (via
  a later `report()` call) or when `flush()`/`close()` is invoked.
- `flush(job_id)` immediately sends the latest pending event for that job, if
  any (no-op otherwise). Callers should flush on job completion/failure so a
  final progress update is never lost to debouncing.
- `close()` flushes every job with a pending event. Intended for shutdown.

Sends are best-effort: `client.progress(...)` is called outside the lock, and
if it raises, the exception is logged and swallowed rather than propagated.
`last_sent_phase`/`last_sent_at` are only updated (and `pending` only cleared)
on a *successful* send, so a failed send leaves the event pending and it will
be retried on the next `report()`/`flush()`/`close()` call.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass

from shared.job_progress import JobProgressEvent, format_current_step

log = logging.getLogger(__name__)

DEFAULT_DEBOUNCE_SEC = 1.5


def _debounce_sec_from_env(default: float) -> float:
    raw = os.getenv("WORKER_PROGRESS_DEBOUNCE_SEC")
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except ValueError:
        return default


@dataclass
class _JobState:
    last_sent_phase: str | None = None
    last_sent_at: float | None = None
    pending: JobProgressEvent | None = None


class ProgressReporter:
    def __init__(self, client, *, debounce_sec: float | None = None) -> None:
        self._client = client
        self._debounce_sec = (
            debounce_sec if debounce_sec is not None else _debounce_sec_from_env(DEFAULT_DEBOUNCE_SEC)
        )
        self._lock = threading.Lock()
        self._state: dict[str, _JobState] = {}

    def report(self, job_id: str, event: JobProgressEvent) -> None:
        with self._lock:
            state = self._state.setdefault(job_id, _JobState())
            is_first = state.last_sent_at is None
            phase_changed = not is_first and event.phase != state.last_sent_phase
            if is_first or phase_changed:
                should_send_now = True
            else:
                now = time.monotonic()
                elapsed = now - state.last_sent_at
                should_send_now = elapsed >= self._debounce_sec
            # Always record as pending first so a failed send below still
            # leaves the event retrievable by a later report()/flush()/close().
            state.pending = event
            if not should_send_now:
                return
        self._send(job_id, state, event)

    def flush(self, job_id: str) -> None:
        with self._lock:
            state = self._state.get(job_id)
            if state is None or state.pending is None:
                return
            event = state.pending
        self._send(job_id, state, event)

    def close(self) -> None:
        with self._lock:
            job_ids = list(self._state.keys())
        for job_id in job_ids:
            self.flush(job_id)

    def _send(self, job_id: str, state: _JobState, event: JobProgressEvent) -> None:
        """Send `event` to the coordinator outside `self._lock` so a slow or
        failing HTTP round-trip for one job never blocks progress reporting
        for other jobs. Best-effort: failures are logged and swallowed so a
        broken PATCH never propagates into job completion/failure handling or
        the annotation job itself. `last_sent_*`/`pending` are only updated
        under the lock, and only after a successful send.
        """
        try:
            self._client.progress(
                job_id,
                format_current_step(event),
                phase=event.phase,
                sections_done=event.sections_done,
                sections_total=event.sections_total,
                pass_name=event.pass_name,
            )
        except Exception:  # noqa: BLE001 - progress updates must never break job execution.
            log.warning("Progress update failed for job %s; will retry", job_id, exc_info=True)
            return
        with self._lock:
            state.last_sent_phase = event.phase
            state.last_sent_at = time.monotonic()
            if state.pending is event:
                state.pending = None
