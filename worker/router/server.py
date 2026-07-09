from __future__ import annotations

import json
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import ollama

from worker.router.router import ModelNotFoundError, ModelRouter


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


def _make_handler(router: ModelRouter, *, collect_metrics: bool):
    class RouterHTTPHandler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args) -> None:
            return

        def do_GET(self) -> None:
            if self.path == "/health":
                _json_response(self, HTTPStatus.OK, {"status": "ok"})
                return
            if self.path == "/metrics":
                _json_response(self, HTTPStatus.OK, {})
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

            queue_start = time.monotonic()
            try:
                backend = router.acquire(model)
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

            try:
                client = ollama.Client(host=backend.host)
                result = client.chat(**chat_kwargs)
                payload = _chat_response_payload(result)
                payload["backend"] = backend.host
                payload["queue_wait_ms"] = queue_wait_ms
                _json_response(self, HTTPStatus.OK, payload)
            except Exception as exc:
                _json_response(
                    self,
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {"error": str(exc)},
                )
            finally:
                router.release(backend)

    RouterHTTPHandler.collect_metrics = collect_metrics
    return RouterHTTPHandler


def start_router_server(
    router: ModelRouter,
    host: str,
    port: int,
    *,
    collect_metrics: bool = False,
) -> threading.Thread:
    handler = _make_handler(router, collect_metrics=collect_metrics)
    server = ThreadingHTTPServer((host, port), handler)
    thread = threading.Thread(target=server.serve_forever, name="router-server", daemon=True)
    thread._server = server  # type: ignore[attr-defined]
    thread._port = server.server_address[1]  # type: ignore[attr-defined]
    thread.start()
    return thread
