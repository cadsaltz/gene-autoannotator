"""Capture managed ``ollama serve`` stdout/stderr for disk + dashboard."""

from __future__ import annotations

import threading
from collections import deque
from pathlib import Path
from typing import Any

from worker.fleet.ollama_diag import summarize_ollama_lines

DEFAULT_RING_SIZE = 1000
DEFAULT_DASHBOARD_LINES = 10
_MAX_LINE_DISPLAY = 120

_log_dir: Path | None = None
_buffers_by_port: dict[int, "OllamaLogBuffer"] = {}
_registry_lock = threading.Lock()


def set_ollama_log_dir(path: Path | None) -> None:
    """Write ``ollama-server-*.log`` under this directory (else cwd)."""
    global _log_dir
    _log_dir = path.resolve() if path is not None else None


def ollama_server_log_path(port: int) -> Path:
    base = _log_dir if _log_dir is not None else Path.cwd()
    return base / f"ollama-server-{port}.log"


def register_buffer(port: int, buffer: "OllamaLogBuffer") -> None:
    with _registry_lock:
        _buffers_by_port[port] = buffer


def get_buffer_for_port(port: int) -> "OllamaLogBuffer | None":
    with _registry_lock:
        return _buffers_by_port.get(port)


def clear_buffers() -> None:
    with _registry_lock:
        _buffers_by_port.clear()


class OllamaLogBuffer:
    """Thread-safe ring buffer of recent Ollama serve log lines."""

    def __init__(self, *, maxlen: int = DEFAULT_RING_SIZE) -> None:
        self._lines: deque[str] = deque(maxlen=max(1, maxlen))
        self._lock = threading.Lock()
        self.log_path: Path | None = None
        self.port: int | None = None

    def append(self, line: str) -> None:
        text = line.rstrip("\n\r")
        if not text:
            return
        with self._lock:
            self._lines.append(text)

    def recent(self, n: int = DEFAULT_DASHBOARD_LINES) -> list[str]:
        with self._lock:
            if n <= 0:
                return []
            return list(self._lines)[-n:]

    def all_lines(self) -> list[str]:
        with self._lock:
            return list(self._lines)

    def summary(self) -> dict[str, Any]:
        return summarize_ollama_lines(self.all_lines()).to_dict()

    def snapshot(
        self,
        *,
        host: str,
        port: int,
        pid: int | None,
        status: str,
        n_lines: int = DEFAULT_DASHBOARD_LINES,
    ) -> dict[str, Any]:
        with self._lock:
            lines = list(self._lines)
        return {
            "host": host,
            "port": port,
            "pid": pid,
            "status": status,
            "log_path": str(self.log_path) if self.log_path is not None else None,
            "lines": lines[-n_lines:] if n_lines > 0 else [],
            "summary": summarize_ollama_lines(lines).to_dict(),
        }


def start_ollama_log_tee(
    proc: Any,
    buffer: OllamaLogBuffer,
    log_path: Path,
) -> threading.Thread:
    """Drain ``proc.stdout`` into ``log_path`` and ``buffer`` (daemon thread)."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    buffer.log_path = log_path

    def _run() -> None:
        stdout = getattr(proc, "stdout", None)
        if stdout is None:
            return
        try:
            with open(log_path, "ab") as fh:
                while True:
                    raw = stdout.readline()
                    if not raw:
                        break
                    if isinstance(raw, str):
                        raw_bytes = raw.encode("utf-8", errors="replace")
                        line = raw
                    else:
                        raw_bytes = raw
                        line = raw.decode("utf-8", errors="replace")
                    try:
                        fh.write(raw_bytes)
                        fh.flush()
                    except Exception:
                        pass
                    buffer.append(line)
        finally:
            try:
                stdout.close()
            except Exception:
                pass

    thread = threading.Thread(
        target=_run,
        name=f"ollama-log-tee-{log_path.name}",
        daemon=True,
    )
    thread.start()
    return thread


def truncate_line_for_display(line: str, *, max_len: int = _MAX_LINE_DISPLAY) -> str:
    text = line.replace("\t", " ")
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"
