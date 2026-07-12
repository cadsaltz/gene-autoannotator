from __future__ import annotations

import json
import logging
import os
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import TYPE_CHECKING

import ollama

from worker.ollama_keep_alive import parse_ollama_keep_alive
from worker.router.inflight import InflightTracker
from worker.router.metrics import MetricsCollector, tokens_from_ollama_result
from worker.router.router import ModelNotFoundError, ModelRouter
from worker.router.timeouts import ollama_chat_timeout

log = logging.getLogger(__name__)

_inflight_tracker: InflightTracker | None = None
_inflight_watchdog_stop: threading.Event | None = None

if TYPE_CHECKING:
    from worker.fleet.config import FleetConfig


def _json_response(handler: BaseHTTPRequestHandler, status: int, payload: dict) -> None:
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _read_json_body(handler: BaseHTTPRequestHandler) -> dict:
    length = int(handler.headers.get("Content-Length", 0))
    if length <= 0:
        return {}
    raw = handler.rfile.read(length)
    return json.loads(raw)


def _chat_response_payload(result: object) -> dict:
    if isinstance(result, dict):
        return dict(result)
    if hasattr(result, "model_dump"):
        return result.model_dump()
    if hasattr(result, "_asdict"):
        return result._asdict()
    return {"result": result}


def _duration_ms_from_ns(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(int(value) / 1_000_000)
    except (TypeError, ValueError):
        return None


def _inference_ms_from_result(result: dict) -> int:
    return _duration_ms_from_ns(result.get("eval_duration")) or 0


def _total_ms_from_result(result: dict, *, queue_wait_ms: int, inference_ms: int) -> int:
    total_ms = _duration_ms_from_ns(result.get("total_duration"))
    if total_ms is not None:
        return total_ms
    return queue_wait_ms + inference_ms


def _ollama_client(host: str):
    timeout = ollama_chat_timeout()
    try:
        return ollama.Client(host=host, timeout=timeout)
    except TypeError:
        return ollama.Client(host=host)


def _parse_keep_alive(value) -> int | str | None:
    return parse_ollama_keep_alive(value)


def _keep_alive_from_env() -> int | str | None:
    raw = os.getenv("AUTOANNOTATION_OLLAMA_KEEP_ALIVE")
    if raw is None or not str(raw).strip():
        return None
    return _parse_keep_alive(raw)


def _inflight_snapshot() -> list[dict[str, object]]:
    if _inflight_tracker is None:
        return []
    return _inflight_tracker.snapshot()


def _start_inflight_watchdog() -> None:
    global _inflight_watchdog_stop
    if _inflight_tracker is None:
        return
    stop = threading.Event()
    _inflight_watchdog_stop = stop

    def _loop() -> None:
        while not stop.wait(30.0):
            _inflight_tracker.maybe_warn_stuck()

    threading.Thread(target=_loop, name="router-inflight-watchdog", daemon=True).start()


def _stop_inflight_watchdog() -> None:
    global _inflight_watchdog_stop
    if _inflight_watchdog_stop is not None:
        _inflight_watchdog_stop.set()
        _inflight_watchdog_stop = None


def _make_handler(
    router: ModelRouter,
    *,
    collect_metrics: bool,
    log_requests: bool = False,
    metrics: MetricsCollector | None = None,
    fleet_cfg: FleetConfig | None = None,
    jobs_submitted: int = 0,
    model_mode: str = "nano",
):
    class RouterHTTPHandler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args) -> None:
            return

        def do_GET(self) -> None:
            if self.path == "/health":
                _json_response(self, HTTPStatus.OK, {"status": "ok"})
                return
            if self.path == "/inflight":
                _json_response(
                    self,
                    HTTPStatus.OK,
                    {"inflight": _inflight_snapshot()},
                )
                return
            if self.path == "/metrics":
                if self.metrics is None:
                    _json_response(self, HTTPStatus.OK, {})
                    return
                if self.fleet_cfg is None:
                    _json_response(self, HTTPStatus.OK, {})
                    return
                report = self.metrics.build_report(
                    fleet_cfg=self.fleet_cfg,
                    jobs_submitted=self.jobs_submitted,
                    model_mode=self.model_mode,
                )
                _json_response(self, HTTPStatus.OK, report)
                return
            _json_response(self, HTTPStatus.NOT_FOUND, {"error": "not found"})

        def do_POST(self) -> None:
            if self.path != "/v1/chat":
                _json_response(self, HTTPStatus.NOT_FOUND, {"error": "not found"})
                return

            try:
                body = _read_json_body(self)
            except json.JSONDecodeError:
                _json_response(self, HTTPStatus.BAD_REQUEST, {"error": "invalid json"})
                return

            model = body.get("model")
            messages = body.get("messages")
            if not model or messages is None:
                _json_response(
                    self,
                    HTTPStatus.BAD_REQUEST,
                    {"error": "model and messages are required"},
                )
                return

            format_ = body.get("format")
            role = body.get("role", "inference")
            job_id = body.get("job_id")

            queue_start = time.monotonic()
            try:
                backend = router.acquire(
                    model,
                    job_id=job_id,
                    role=role,
                    log_waits=self.log_requests,
                )
            except ModelNotFoundError as exc:
                _json_response(
                    self,
                    HTTPStatus.BAD_REQUEST,
                    {"error": str(exc), "known_models": sorted(exc.known)},
                )
                return

            queue_wait_ms = int((time.monotonic() - queue_start) * 1000)

            chat_kwargs: dict = {"model": model, "messages": messages}
            if format_ is not None:
                chat_kwargs["format"] = format_
            keep_alive = _parse_keep_alive(body.get("keep_alive"))
            if keep_alive is None:
                keep_alive = _keep_alive_from_env()
            if keep_alive is not None:
                chat_kwargs["keep_alive"] = keep_alive

            if self.log_requests:
                log.info(
                    "router dispatch job=%s model=%s role=%s backend=%s queue=%dms",
                    job_id or "-",
                    model,
                    role,
                    backend.host,
                    queue_wait_ms,
                )

            inflight_id: int | None = None
            try:
                client = _ollama_client(backend.host)
                if _inflight_tracker is not None:
                    inflight_id = _inflight_tracker.start(
                        job_id=job_id,
                        model=model,
                        role=role,
                        backend=backend.host,
                    )
                result = client.chat(**chat_kwargs)
                payload = _chat_response_payload(result)
                inference_ms = _inference_ms_from_result(payload)
                total_ms = _total_ms_from_result(
                    payload,
                    queue_wait_ms=queue_wait_ms,
                    inference_ms=inference_ms,
                )
                input_tokens, output_tokens, total_tokens = tokens_from_ollama_result(payload)
                if self.metrics is not None:
                    self.metrics.record_call(
                        model=model,
                        role=role,
                        backend=backend.host,
                        queue_wait_ms=queue_wait_ms,
                        inference_ms=inference_ms,
                        total_ms=total_ms,
                        job_id=job_id,
                        success=True,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        total_tokens=total_tokens,
                    )
                if self.log_requests:
                    log.info(
                        "router chat job=%s model=%s role=%s backend=%s "
                        "queue=%dms infer=%dms total=%dms",
                        job_id or "-",
                        model,
                        role,
                        backend.host,
                        queue_wait_ms,
                        inference_ms,
                        total_ms,
                    )
                payload["backend"] = backend.host
                payload["queue_wait_ms"] = queue_wait_ms
                _json_response(self, HTTPStatus.OK, payload)
            except Exception as exc:
                log.error(
                    "router chat failed job=%s model=%s role=%s backend=%s: %s",
                    job_id or "-",
                    model,
                    role,
                    backend.host,
                    exc,
                )
                if self.metrics is not None:
                    self.metrics.record_call(
                        model=model,
                        role=role,
                        backend=backend.host,
                        queue_wait_ms=queue_wait_ms,
                        inference_ms=0,
                        total_ms=queue_wait_ms,
                        job_id=job_id,
                        success=False,
                    )
                _json_response(
                    self,
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {"error": str(exc)},
                )
            finally:
                if inflight_id is not None and _inflight_tracker is not None:
                    _inflight_tracker.finish(inflight_id)
                router.release(backend, model)

    RouterHTTPHandler.collect_metrics = collect_metrics
    RouterHTTPHandler.log_requests = log_requests
    RouterHTTPHandler.metrics = metrics
    RouterHTTPHandler.fleet_cfg = fleet_cfg
    RouterHTTPHandler.jobs_submitted = jobs_submitted
    RouterHTTPHandler.model_mode = model_mode
    return RouterHTTPHandler


def start_router_server(
    router: ModelRouter,
    host: str,
    port: int,
    *,
    collect_metrics: bool = False,
    log_requests: bool = False,
    fleet_cfg: FleetConfig | None = None,
    jobs_submitted: int = 0,
    model_mode: str = "nano",
) -> threading.Thread:
    global _inflight_tracker
    metrics: MetricsCollector | None = None
    if collect_metrics:
        metrics = MetricsCollector()
        metrics.begin_batch()

    if log_requests or collect_metrics:
        _inflight_tracker = InflightTracker()
        _start_inflight_watchdog()
    else:
        _inflight_tracker = None

    handler = _make_handler(
        router,
        collect_metrics=collect_metrics,
        log_requests=log_requests,
        metrics=metrics,
        fleet_cfg=fleet_cfg,
        jobs_submitted=jobs_submitted,
        model_mode=model_mode,
    )
    server = ThreadingHTTPServer((host, port), handler)
    thread = threading.Thread(target=server.serve_forever, name="router-server", daemon=True)
    thread._server = server  # type: ignore[attr-defined]
    thread._port = server.server_address[1]  # type: ignore[attr-defined]
    thread._metrics = metrics  # type: ignore[attr-defined]
    thread.start()
    return thread


def stop_router_server(thread: threading.Thread) -> None:
    _stop_inflight_watchdog()
    server = getattr(thread, "_server", None)
    if server is not None:
        server.shutdown()
        server.server_close()
    thread.join(timeout=2.0)
