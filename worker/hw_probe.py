from __future__ import annotations

import csv
import io
import logging
import shutil
import subprocess
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


def probe_ollama_cpu_percent() -> float | None:
    """Approximate Ollama CPU usage from /proc (v1: not implemented).

    A future version would scan /proc/[pid]/comm for names containing ``ollama``,
    read utime/stime from /proc/[pid]/stat, and sum deltas across processes over
    a refresh interval. Returns ``None`` when unavailable or not yet sampled.
    """
    return None
