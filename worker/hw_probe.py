from __future__ import annotations

import csv
import io
import logging
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

_PROC_ROOT = Path("/proc")

_NVIDIA_SMI_QUERY = [
    "nvidia-smi",
    "--query-gpu=index,name,utilization.gpu,memory.used,memory.total,temperature.gpu",
    "--format=csv,noheader,nounits",
]


@dataclass(frozen=True)
class GpuStat:
    index: int
    name: str
    util_percent: float
    mem_used_mb: int
    mem_total_mb: int
    temp_c: float


@dataclass(frozen=True)
class GpuUnavailable:
    reason: str


@dataclass(frozen=True)
class ProcStatSample:
    idle: int
    total: int


@dataclass(frozen=True)
class CpuRamStat:
    cpu_percent: float | None
    total_bytes: int
    available_bytes: int


@dataclass(frozen=True)
class OllamaCpuSample:
    """Sum of utime+stime jiffies across matching Ollama processes."""

    jiffies: int
    process_count: int
    monotonic: float


@dataclass(frozen=True)
class OllamaCpuStat:
    """Ollama fleet CPU use over a refresh interval.

    ``percent`` matches ``top``/``htop`` style (can exceed 100 on multi-core).
    ``cores`` is ``percent / 100`` — approximate logical cores in use.
    """

    percent: float
    cores: float
    process_count: int


def parse_nvidia_smi_csv(raw: str) -> list[GpuStat] | GpuUnavailable:
    text = raw.strip()
    if not text:
        return GpuUnavailable(reason="empty nvidia-smi output")

    gpus: list[GpuStat] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        parsed = _parse_nvidia_smi_line(line)
        if parsed is None:
            log.debug("Skipping unparseable nvidia-smi line: %r", line)
            continue
        gpus.append(parsed)

    if not gpus:
        return GpuUnavailable(reason="no parseable GPU rows in nvidia-smi output")
    return gpus


def _parse_nvidia_smi_line(line: str) -> GpuStat | None:
    try:
        parts = next(csv.reader(io.StringIO(line)))
        if len(parts) < 6:
            return None
        return GpuStat(
            index=int(parts[0].strip()),
            name=", ".join(part.strip() for part in parts[1:-4]),
            util_percent=float(parts[-4].strip()),
            mem_used_mb=int(float(parts[-3].strip())),
            mem_total_mb=int(float(parts[-2].strip())),
            temp_c=float(parts[-1].strip()),
        )
    except (StopIteration, ValueError):
        return None


def probe_gpus() -> list[GpuStat] | GpuUnavailable:
    if shutil.which("nvidia-smi") is None:
        return GpuUnavailable(reason="nvidia-smi not found")

    try:
        result = subprocess.run(
            _NVIDIA_SMI_QUERY,
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return GpuUnavailable(reason="nvidia-smi not found")

    if result.returncode != 0:
        return GpuUnavailable(
            reason=f"nvidia-smi exited with code {result.returncode}",
        )

    parsed = parse_nvidia_smi_csv(result.stdout)
    if isinstance(parsed, GpuUnavailable):
        return parsed
    return parsed


def parse_meminfo(raw: str) -> CpuRamStat:
    total_kb: int | None = None
    available_kb: int | None = None
    for line in raw.splitlines():
        if line.startswith("MemTotal:"):
            total_kb = _parse_meminfo_kb(line)
        elif line.startswith("MemAvailable:"):
            available_kb = _parse_meminfo_kb(line)
    return CpuRamStat(
        cpu_percent=None,
        total_bytes=(total_kb or 0) * 1024,
        available_bytes=(available_kb or 0) * 1024,
    )


def _parse_meminfo_kb(line: str) -> int | None:
    parts = line.split()
    if len(parts) < 2:
        return None
    try:
        return int(parts[1])
    except ValueError:
        return None


def read_proc_stat_sample() -> ProcStatSample | None:
    stat_path = _PROC_ROOT / "stat"
    try:
        first_line = stat_path.read_text(encoding="utf-8").splitlines()[0]
    except (OSError, IndexError):
        return None
    return _parse_proc_stat_line(first_line)


def _parse_proc_stat_line(line: str) -> ProcStatSample | None:
    if not line.startswith("cpu "):
        return None
    try:
        fields = [int(value) for value in line.split()[1:]]
    except ValueError:
        return None
    if len(fields) < 4:
        return None
    idle = fields[3]
    if len(fields) >= 5:
        idle += fields[4]
    total = sum(fields)
    return ProcStatSample(idle=idle, total=total)


def cpu_percent_from_samples(prev: ProcStatSample, curr: ProcStatSample) -> float | None:
    delta_total = curr.total - prev.total
    delta_idle = curr.idle - prev.idle
    if delta_total <= 0:
        return None
    used = delta_total - delta_idle
    return max(0.0, min(100.0, (used / delta_total) * 100.0))


def probe_cpu_ram(*, prev_stat_sample: ProcStatSample | None = None) -> CpuRamStat:
    mem = parse_meminfo((_PROC_ROOT / "meminfo").read_text(encoding="utf-8"))
    cpu_percent: float | None = None
    current_sample = read_proc_stat_sample()
    if prev_stat_sample is not None and current_sample is not None:
        cpu_percent = cpu_percent_from_samples(prev_stat_sample, current_sample)
    return CpuRamStat(
        cpu_percent=cpu_percent,
        total_bytes=mem.total_bytes,
        available_bytes=mem.available_bytes,
    )


def _clock_ticks_per_sec() -> int:
    try:
        return int(os.sysconf("SC_CLK_TCK"))
    except (AttributeError, ValueError, OSError):
        return 100


def _read_proc_comm(pid: int) -> str | None:
    try:
        return (_PROC_ROOT / str(pid) / "comm").read_text(encoding="utf-8").strip()
    except OSError:
        return None


def _read_proc_stat_jiffies(pid: int) -> int | None:
    try:
        stat = (_PROC_ROOT / str(pid) / "stat").read_text(encoding="utf-8")
    except OSError:
        return None
    rparen = stat.rfind(")")
    if rparen == -1:
        return None
    fields = stat[rparen + 2 :].split()
    if len(fields) < 13:
        return None
    try:
        utime = int(fields[11])
        stime = int(fields[12])
    except ValueError:
        return None
    return utime + stime


def _ollama_pids() -> list[int]:
    pids: list[int] = []
    try:
        entries = _PROC_ROOT.iterdir()
    except OSError:
        return pids
    for entry in entries:
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        comm = _read_proc_comm(pid)
        if comm == "ollama":
            pids.append(pid)
    return pids


def read_ollama_cpu_sample() -> OllamaCpuSample:
    jiffies = 0
    count = 0
    for pid in _ollama_pids():
        proc_jiffies = _read_proc_stat_jiffies(pid)
        if proc_jiffies is None:
            continue
        jiffies += proc_jiffies
        count += 1
    return OllamaCpuSample(
        jiffies=jiffies,
        process_count=count,
        monotonic=time.monotonic(),
    )


def ollama_cpu_from_samples(
    prev: OllamaCpuSample,
    curr: OllamaCpuSample,
) -> OllamaCpuStat | None:
    delta_t = curr.monotonic - prev.monotonic
    if delta_t <= 0:
        return None
    delta_jiffies = curr.jiffies - prev.jiffies
    if delta_jiffies < 0:
        return None
    clk_tck = _clock_ticks_per_sec()
    percent = 100.0 * delta_jiffies / (delta_t * clk_tck)
    percent = max(0.0, percent)
    return OllamaCpuStat(
        percent=percent,
        cores=percent / 100.0,
        process_count=curr.process_count,
    )


def probe_ollama_cpu(
    *,
    prev_sample: OllamaCpuSample | None = None,
) -> tuple[OllamaCpuStat | None, OllamaCpuSample]:
    """Measure Ollama CPU from ``/proc`` (no Ollama CLI/HTTP).

    Returns the current sample always; ``OllamaCpuStat`` only when ``prev_sample``
    is provided and the interval is valid. First dashboard tick is usually ``None``.
    """
    current = read_ollama_cpu_sample()
    if prev_sample is None:
        return None, current
    return ollama_cpu_from_samples(prev_sample, current), current


def probe_ollama_cpu_percent() -> float | None:
    """Backward-compatible helper; prefer :func:`probe_ollama_cpu`."""
    stat, _ = probe_ollama_cpu()
    return stat.percent if stat is not None else None
