from __future__ import annotations

import subprocess
import time
from pathlib import Path

from worker.fleet.ollama_log import (
    OllamaLogBuffer,
    clear_buffers,
    get_buffer_for_port,
    register_buffer,
    set_ollama_log_dir,
    start_ollama_log_tee,
    truncate_line_for_display,
)
from worker.bench_dashboard import render_dashboard
from worker.fleet.supervisor import FleetSupervisor
from worker.fleet.config import FleetConfig
from worker.probe import SystemSpec


def test_ollama_log_buffer_ring_truncates():
    buf = OllamaLogBuffer(maxlen=3)
    for i in range(5):
        buf.append(f"line-{i}")
    assert buf.recent(10) == ["line-2", "line-3", "line-4"]


def test_truncate_line_for_display():
    assert truncate_line_for_display("short") == "short"
    long = "x" * 200
    out = truncate_line_for_display(long, max_len=20)
    assert len(out) == 20
    assert out.endswith("…")


def test_start_ollama_log_tee_captures_lines(tmp_path: Path):
    set_ollama_log_dir(tmp_path)
    clear_buffers()
    log_path = tmp_path / "ollama-server-11434.log"
    buffer = OllamaLogBuffer()
    register_buffer(11434, buffer)
    proc = subprocess.Popen(
        ["bash", "-c", "printf 'hello\\nworld\\n'; sleep 0.2"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=0,
    )
    start_ollama_log_tee(proc, buffer, log_path)
    proc.wait(timeout=5)
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline and len(buffer.recent(10)) < 2:
        time.sleep(0.05)
    assert buffer.recent(10) == ["hello", "world"]
    assert log_path.read_text(encoding="utf-8") == "hello\nworld\n"
    assert get_buffer_for_port(11434) is buffer


def test_render_dashboard_includes_ollama_section():
    text = render_dashboard(
        snapshot={"jobs_completed": 1, "jobs_total": None, "jobs_failed": 0, "active": []},
        hw={"gpus": None, "gpu_error": "no gpu", "cpu_percent": 1.0, "ram": "1/8 GB"},
        meta={
            "mode": "serve",
            "fleet": "1x1",
            "ollama_servers": [
                {
                    "host": "http://127.0.0.1:11434",
                    "port": 11434,
                    "pid": 4242,
                    "status": "running",
                    "log_path": "/tmp/ollama-server-11434.log",
                    "lines": ["listening on 127.0.0.1:11434", "llama runner started"],
                }
            ],
        },
    )
    assert "OLLAMA" in text
    assert "pid 4242 running" in text
    assert "listening on 127.0.0.1:11434" in text
    assert "/tmp/ollama-server-11434.log" in text


def test_supervisor_ollama_log_snapshot_includes_buffer():
    clear_buffers()
    cfg = FleetConfig(
        num_servers=1,
        parallel=1,
        max_slots=1,
        w_all_bytes=1,
        c_slot_bytes=1,
    )
    spec = SystemSpec(
        gpu_count=1,
        vram_bytes=(8 * 1024**3,),
        system_ram_bytes=16 * 1024**3,
        cpu_physical=4,
        cpu_logical=8,
    )
    buffer = OllamaLogBuffer()
    buffer.log_path = Path("/tmp/ollama-server-11434.log")
    buffer.append("boot ok")
    register_buffer(11434, buffer)

    class FakeProc:
        pid = 99

        def poll(self):
            return None

    supervisor = FleetSupervisor(cfg, spec)
    supervisor.attach_started(
        host="http://127.0.0.1:11434",
        port=11434,
        parallel=1,
        gpu_index=0,
        max_loaded_models=1,
        proc=FakeProc(),  # type: ignore[arg-type]
        log_buffer=buffer,
    )
    snap = supervisor.ollama_log_snapshot()
    assert len(snap) == 1
    assert snap[0]["status"] == "running"
    assert snap[0]["pid"] == 99
    assert snap[0]["lines"] == ["boot ok"]
