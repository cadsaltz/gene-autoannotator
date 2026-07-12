from __future__ import annotations

import json
import logging
import os
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import TYPE_CHECKING

import httpx

from worker.ollama_keep_alive import parse_ollama_keep_alive
from worker.router.metrics import MetricsCollector, tokens_from_ollama_result
from worker.router.ollama_http import chat as ollama_chat_http
from worker.router.router import ModelNotFoundError, ModelRouter
from worker.router.timeouts import ollama_chat_timeout_for_role

log = logging.getLogger(__name__)

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


def _parse_keep_alive(value) -> int | str | None:
    return parse_ollama_keep_alive(value)


def _keep_alive_from_env() -> int | str | None:
    raw = os.getenv("AUTOANNOTATION_OLLAMA_KEEP_ALIVE")
    if raw is None or not str(raw).strip():
        return None
    return _parse_keep_alive(raw)


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
                backend = router.acquire(model, job_id=job_id, role=role)
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

            timeout_sec = ollama_chat_timeout_for_role(role)

            if self.log_requests:
                log.info(
                    "router dispatch job=%s model=%s role=%s backend=%s queue=%dms timeout=%ds",
                    job_id or "-",
                    model,
                    role,
                    backend.host,
                    queue_wait_ms,
                    int(timeout_sec),
                )

            try:
                result = ollama_chat_http(
                    backend.host,
                    timeout_sec=timeout_sec,
                    **chat_kwargs,
                )
                inference_ms = _inference_ms_from_result(result)
                total_ms = _total_ms_from_result(
                    result,
                    queue_wait_ms=queue_wait_ms,
                    inference_ms=inference_ms,
                )
                input_tokens, output_tokens, total_tokens = tokens_from_ollama_result(result)
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
                result = dict(result)
                result["backend"] = backend.host
                result["queue_wait_ms"] = queue_wait_ms
                _json_response(self, HTTPStatus.OK, result)
            except httpx.TimeoutException as exc:
                log.error(
                    "router chat timed out job=%s model=%s role=%s backend=%s after %ds",
                    job_id or "-",
                    model,
                    role,
                    backend.host,
                    int(timeout_sec),
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
                    HTTPStatus.GATEWAY_TIMEOUT,
                    {
                        "error": (
                            f"Ollama chat timed out after {int(timeout_sec)}s "
                            f"(role={role})"
                        ),
                    },
                )
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
    metrics: MetricsCollector | None = None
    if collect_metrics:
        metrics = MetricsCollector()
        metrics.begin_batch()

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
    server = getattr(thread, "_server", None)
    if server is not None:
        server.shutdown()
        server.server_close()
    thread.join(timeout=2.0)
