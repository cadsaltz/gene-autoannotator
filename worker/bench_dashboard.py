from __future__ import annotations

import logging
import threading
import time
from typing import Any

from rich.console import Group
from rich.live import Live
from rich.text import Text

from worker import hw_probe
from worker.hw_probe import CpuRamStat, GpuStat, GpuUnavailable, OllamaCpuStat, OllamaCpuSample, ProcStatSample

log = logging.getLogger(__name__)

SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
_SEPARATOR = "─" * 40


def _jobs_done(snapshot: dict[str, Any]) -> int:
    for key in ("jobs_completed", "jobs_done"):
        value = snapshot.get(key)
        if isinstance(value, int):
            return value
    return 0


def _format_elapsed(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    total = max(0, int(seconds))
    minutes, secs = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def _format_job_elapsed(seconds: float) -> str:
    return f"{max(0.0, seconds):.0f}s"


def _format_percent(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:.0f}%"


def _format_ollama_cpu(stat: OllamaCpuStat | None) -> str:
    if stat is None:
        return "—"
    if stat.process_count == 0:
        return "0% (no processes)"
    cores_label = f"{stat.cores:.1f}".rstrip("0").rstrip(".")
    return f"{stat.percent:.0f}% (~{cores_label} cores)"


def _progress_sections(progress: dict[str, Any] | None) -> str:
    if not progress:
        return "—"
    done = progress.get("sections_done")
    total = progress.get("sections_total")
    if done is None and total is None:
        return progress.get("phase") or progress.get("current_step") or "—"
    if total is None:
        return f"{done}/?"
    return f"{done}/{total}"


def _job_phase(progress: dict[str, Any] | None) -> str:
    if not progress:
        return "—"
    phase = progress.get("phase")
    if isinstance(phase, str) and phase:
        return phase
    current = progress.get("current_step")
    if isinstance(current, str) and current:
        return current.split()[0]
    return "—"


def _build_lines(
    *,
    snapshot: dict[str, Any],
    hw: dict[str, Any],
    meta: dict[str, Any] | None = None,
    spinner_frame: str = SPINNER_FRAMES[0],
) -> list[str]:
    meta = meta or {}
    mode = meta.get("mode", "bench")
    is_serve = mode == "serve"
    jobs_done = _jobs_done(snapshot)
    jobs_total = snapshot.get("jobs_total")
    jobs_failed = int(snapshot.get("jobs_failed") or 0)
    active = snapshot.get("active") or []
    running = len(active)
    total_display = str(jobs_total) if isinstance(jobs_total, int) else "?"
    queued = 0
    if isinstance(jobs_total, int):
        queued = max(0, jobs_total - jobs_done - jobs_failed - running)

    product = "gene-autoannotator serve" if is_serve else "gene-autoannotator bench"
    time_label = "uptime" if is_serve else "elapsed"
    header_bits = [
        product,
        mode,
        f"fleet {meta.get('fleet', '—')}",
        f"slots {meta.get('slots', '—')}",
        f"tier {meta.get('tier', '—')}",
        f"{time_label} {_format_elapsed(meta.get('elapsed_s'))}",
    ]
    if is_serve:
        summary_line = f"SERVE  {jobs_done} done │ {jobs_failed} failed │ {running} running"
    else:
        summary_line = (
            f"BATCH  {jobs_done}/{total_display} │ {jobs_failed} failed │ "
            f"{running} running │ {queued} queued"
        )
    lines = [
        "",
        " │ ".join(str(bit) for bit in header_bits),
        summary_line,
        "",
        _SEPARATOR,
        "",
        "JOBS",
    ]

    if active:
        for job in active:
            progress = job.get("progress")
            lines.append(
                "  "
                f"{spinner_frame} "
                f"{job.get('job_id', '?')}  |  "
                f"{job.get('locus', '?')}  |  "
                f"phase {_job_phase(progress)}  |  "
                f"sections {_progress_sections(progress)}  |  "
                f"elapsed {_format_job_elapsed(float(job.get('elapsed_s') or 0.0))}"
            )
    else:
        lines.append("  (no active jobs)")

    lines.append("")
    lines.append(_SEPARATOR)
    lines.append("")

    gpus = hw.get("gpus")
    gpu_error = hw.get("gpu_error")
    if isinstance(gpus, list) and gpus:
        for gpu in gpus:
            if isinstance(gpu, GpuStat):
                lines.append(
                    f"GPU {gpu.index}  |  {gpu.name}  |  "
                    f"util {gpu.util_percent:.0f}%  |  "
                    f"mem {gpu.mem_used_mb}/{gpu.mem_total_mb} MB VRAM  |  "
                    f"temp {gpu.temp_c:.0f}°C"
                )
            elif isinstance(gpu, dict):
                lines.append(
                    f"GPU {gpu.get('index', '?')}  |  {gpu.get('name', '?')}  |  "
                    f"util {gpu.get('util_percent', '?')}%  |  "
                    f"mem {gpu.get('mem_used_mb', '?')}/{gpu.get('mem_total_mb', '?')} MB VRAM"
                )
    elif gpu_error:
        lines.append(f"GPU unavailable: {gpu_error}")
    else:
        lines.append("GPU unavailable")

    ollama_cpu = hw.get("ollama_cpu")
    if not isinstance(ollama_cpu, OllamaCpuStat):
        ollama_cpu = None
    lines.append(
        f"CPU util {_format_percent(hw.get('cpu_percent'))} │ "
        f"Ollama CPU {_format_ollama_cpu(ollama_cpu)} │ "
        f"RAM {hw.get('ram', '—')}"
    )
    lines.extend(_ollama_log_lines(meta))
    lines.extend(_models_in_mem_lines(meta))
    lines.append("")
    lines.append(_SEPARATOR)

    footer = meta.get("status") or meta.get("last_error")
    if footer:
        lines.append("")
        lines.append(str(footer))

    return lines


def _format_gib(nbytes: int | float) -> str:
    return f"{float(nbytes) / (1024**3):.1f} GiB"


def _flight_dots(*, in_flight: int, slots: int, pending: bool = False) -> str:
    """Render slot occupancy: ● busy, ◐ waiting/loading, ○ free."""
    width = max(1, int(slots))
    busy = max(0, min(int(in_flight), width))
    mark = "◐" if pending else "●"
    return (mark * busy) + ("○" * (width - busy))


def _models_in_mem_lines(meta: dict[str, Any]) -> list[str]:
    snap = meta.get("models_in_mem")
    if not isinstance(snap, dict):
        return []
    models = snap.get("models")
    used = snap.get("used_bytes")
    budget = snap.get("budget_bytes")
    if not isinstance(used, (int, float)) or not isinstance(budget, (int, float)):
        return []
    if not isinstance(models, list):
        return []
    slots_raw = meta.get("slots")
    try:
        slots = max(1, int(slots_raw))
    except (TypeError, ValueError):
        slots = 1
    pct = 0 if budget <= 0 else int(round(100.0 * float(used) / float(budget)))
    if snap.get("ps_disabled"):
        header = "IN MEM  (ollama ps disabled — in-flight only)"
    else:
        header = (
            f"IN MEM  {float(used) / (1024**3):.1f}/{float(budget) / (1024**3):.1f} GiB ({pct}%)"
        )
    out = ["", header]
    if not models:
        return out

    ollama_phase = _ollama_phase_hint(meta)
    rows: list[tuple[str, str, str, str]] = []
    waiting_load = False
    for row in models:
        if not isinstance(row, dict):
            continue
        model = row.get("model")
        size = row.get("size_bytes")
        in_flight = row.get("in_flight")
        if not isinstance(model, str) or not model:
            continue
        if not isinstance(size, (int, float)):
            continue
        try:
            flight = int(in_flight)
        except (TypeError, ValueError):
            flight = 0
        size_label = _format_gib(size) if size > 0 else "—"
        note = ""
        pending = False
        if flight > 0 and size <= 0:
            waiting_load = True
            pending = True
            note = "waiting on Ollama load"
        elif flight > 0 and ollama_phase == "loading" and size > 0:
            # Resident size may already show while layers are still uploading.
            pending = True
            note = "loading into memory"
        rows.append(
            (
                _flight_dots(in_flight=flight, slots=slots, pending=pending),
                model,
                size_label,
                note,
            )
        )
    if not rows:
        return out
    name_width = max(len(model) for _, model, _, _ in rows)
    size_width = max(len(size_label) for _, _, size_label, _ in rows)
    for dots, model, size_label, note in rows:
        line = f"  {dots}  {model:<{name_width}}  {size_label:<{size_width}}"
        if note:
            line = f"{line}  |  {note}"
        out.append(line)
    if waiting_load:
        out.append(
            "  (chat in flight; Ollama cold-start / runner spawn before VRAM fills)"
        )
    return out


def _ollama_phase_hint(meta: dict[str, Any]) -> str | None:
    servers = meta.get("ollama_servers")
    if not isinstance(servers, list):
        return None
    phases: list[str] = []
    for server in servers:
        if not isinstance(server, dict):
            continue
        summary = server.get("summary")
        phase = None
        if isinstance(summary, dict):
            phase = summary.get("phase")
        if phase is None:
            phase = server.get("phase")
        if isinstance(phase, str) and phase:
            phases.append(phase)
    if "loading" in phases:
        return "loading"
    if phases:
        return phases[0]
    return None


def _ollama_log_lines(meta: dict[str, Any]) -> list[str]:
    from worker.fleet.ollama_diag import format_summary_lines

    servers = meta.get("ollama_servers")
    if not isinstance(servers, list) or not servers:
        return []
    waiting_models = _waiting_on_load_models(meta)
    out: list[str] = [""]
    for server in servers:
        if not isinstance(server, dict):
            continue
        host = server.get("host") or f"port {server.get('port', '?')}"
        status = server.get("status") or "?"
        pid = server.get("pid")
        pid_part = f"pid {pid}" if pid is not None else "pid —"
        log_path = server.get("log_path") or "—"
        out.append(f"OLLAMA  |  {host}  |  {pid_part} {status}  |  {log_path}")
        summary = server.get("summary")
        if isinstance(summary, dict) and summary:
            lines = format_summary_lines(summary)
            phase = summary.get("phase") or "unknown"
            if phase == "unknown" and waiting_models:
                names = ", ".join(waiting_models)
                out.append(
                    f"  phase: waiting on load | chats held for {names} "
                    f"(cold-start before VRAM)"
                )
                # Keep any alert lines from the formatter after the first phase line.
                out.extend(lines[1:])
            else:
                out.extend(lines)
        elif waiting_models:
            names = ", ".join(waiting_models)
            out.append(
                f"  phase: waiting on load | chats held for {names} "
                f"(cold-start before VRAM)"
            )
        else:
            out.append("  phase: unknown | (waiting for serve logs)")
    return out


def _waiting_on_load_models(meta: dict[str, Any]) -> list[str]:
    snap = meta.get("models_in_mem")
    if not isinstance(snap, dict):
        return []
    models = snap.get("models")
    if not isinstance(models, list):
        return []
    waiting: list[str] = []
    for row in models:
        if not isinstance(row, dict):
            continue
        name = row.get("model")
        size = row.get("size_bytes")
        flight = row.get("in_flight")
        if not isinstance(name, str) or not name:
            continue
        try:
            size_i = int(size or 0)
        except (TypeError, ValueError):
            size_i = 0
        try:
            flight_i = int(flight or 0)
        except (TypeError, ValueError):
            flight_i = 0
        if flight_i > 0 and size_i <= 0:
            waiting.append(name)
    return waiting


def render_dashboard(
    *,
    snapshot: dict[str, Any],
    hw: dict[str, Any],
    meta: dict[str, Any] | None = None,
    spinner_frame: str = SPINNER_FRAMES[0],
) -> str:
    return "\n".join(
        _build_lines(
            snapshot=snapshot,
            hw=hw,
            meta=meta,
            spinner_frame=spinner_frame,
        )
    )


def _format_ram(stat: CpuRamStat) -> str:
    if stat.total_bytes <= 0:
        return "—"
    used_gb = (stat.total_bytes - stat.available_bytes) / (1024**3)
    total_gb = stat.total_bytes / (1024**3)
    return f"{used_gb:.0f}/{total_gb:.0f} GB"


def _probe_hw(
    prev_sample: ProcStatSample | None,
    prev_ollama_sample: OllamaCpuSample | None,
) -> tuple[dict[str, Any], ProcStatSample | None, OllamaCpuSample | None]:
    gpus: list[GpuStat] | None = None
    gpu_error: str | None = None
    try:
        gpu_result = hw_probe.probe_gpus()
        if isinstance(gpu_result, GpuUnavailable):
            gpu_error = gpu_result.reason
        else:
            gpus = gpu_result
    except Exception as exc:
        log.debug("GPU probe failed", exc_info=exc)
        gpu_error = str(exc)

    cpu_percent: float | None = None
    ram = "—"
    next_sample = prev_sample
    try:
        cpu_ram = hw_probe.probe_cpu_ram(prev_stat_sample=prev_sample)
        cpu_percent = cpu_ram.cpu_percent
        ram = _format_ram(cpu_ram)
        next_sample = hw_probe.read_proc_stat_sample()
    except Exception as exc:
        log.debug("CPU/RAM probe failed", exc_info=exc)

    ollama_cpu: OllamaCpuStat | None = None
    next_ollama_sample = prev_ollama_sample
    try:
        ollama_cpu, next_ollama_sample = hw_probe.probe_ollama_cpu(
            prev_sample=prev_ollama_sample,
        )
    except Exception as exc:
        log.debug("Ollama CPU probe failed", exc_info=exc)
        try:
            _, next_ollama_sample = hw_probe.probe_ollama_cpu()
        except Exception:
            pass

    return (
        {
            "gpus": gpus,
            "gpu_error": gpu_error,
            "cpu_percent": cpu_percent,
            "ollama_cpu": ollama_cpu,
            "ram": ram,
        },
        next_sample,
        next_ollama_sample,
    )


class BenchDashboard:
    def render(
        self,
        snapshot: dict[str, Any],
        hw: dict[str, Any],
        *,
        meta: dict[str, Any] | None = None,
        spinner_frame: str = SPINNER_FRAMES[0],
    ) -> str:
        return render_dashboard(
            snapshot=snapshot,
            hw=hw,
            meta=meta,
            spinner_frame=spinner_frame,
        )

    def run_live(
        self,
        runtime: Any,
        stop_event: threading.Event,
        *,
        refresh_sec: float = 0.5,
        meta: dict[str, Any] | None = None,
        meta_provider: Any | None = None,
    ) -> None:
        prev_sample: ProcStatSample | None = None
        prev_ollama_sample: OllamaCpuSample | None = None
        frame_idx = 0
        started_at = time.monotonic()
        live: Live | None = None
        try:
            live = Live(
                Text(""),
                refresh_per_second=max(1.0, 1.0 / refresh_sec),
                transient=False,
            )
            live.start()
            while not stop_event.is_set():
                try:
                    snapshot = runtime.snapshot()
                except Exception as exc:
                    log.debug("Runtime snapshot failed", exc_info=exc)
                    snapshot = {
                        "jobs_completed": 0,
                        "jobs_failed": 0,
                        "jobs_total": None,
                        "active": [],
                    }

                hw, prev_sample, prev_ollama_sample = _probe_hw(
                    prev_sample,
                    prev_ollama_sample,
                )

                live_meta = dict(meta or {})
                # Always refresh elapsed before meta_provider so a slow provider
                # cannot freeze the clock on the previous frame.
                live_meta["elapsed_s"] = time.monotonic() - started_at
                if meta_provider is not None:
                    try:
                        provided = meta_provider()
                        if isinstance(provided, dict):
                            live_meta.update(provided)
                    except Exception as exc:
                        log.debug("Meta provider failed", exc_info=exc)
                live_meta["elapsed_s"] = time.monotonic() - started_at

                text = render_dashboard(
                    snapshot=snapshot,
                    hw=hw,
                    meta=live_meta,
                    spinner_frame=SPINNER_FRAMES[frame_idx % len(SPINNER_FRAMES)],
                )
                live.update(Group(*[Text(line) for line in text.splitlines()]))
                frame_idx += 1
                if stop_event.wait(refresh_sec):
                    break
        except Exception as exc:
            log.debug("Dashboard live loop failed", exc_info=exc)
        finally:
            if live is not None:
                try:
                    live.stop()
                except Exception:
                    pass
