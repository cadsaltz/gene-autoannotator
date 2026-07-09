from __future__ import annotations

import csv
import io
import logging
import shutil
import subprocess
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class SystemSpec:
    gpu_count: int
    vram_bytes: tuple[int, ...]
    system_ram_bytes: int
    cpu_physical: int
    cpu_logical: int

    @property
    def vram_total_bytes(self) -> int:
        return sum(self.vram_bytes)


def _probe_system_ram_bytes() -> int:
    try:
        import psutil

        return int(psutil.virtual_memory().total)
    except Exception:  # noqa: BLE001
        return 0


def _probe_cpu_counts() -> tuple[int, int]:
    try:
        import psutil

        physical = psutil.cpu_count(logical=False) or 1
        logical = psutil.cpu_count(logical=True) or 1
        return physical, logical
    except Exception:  # noqa: BLE001
        return 1, 1


def _parse_vram_line(line: str) -> int | None:
    try:
        parts = next(csv.reader(io.StringIO(line)))
        if len(parts) < 3:
            return None
        return int(float(parts[-1].strip()) * 1024 * 1024)
    except (StopIteration, ValueError):
        return None


def _probe_gpus() -> tuple[int, tuple[int, ...]]:
    if shutil.which("nvidia-smi") is None:
        return 0, ()
    result = subprocess.run(
        [
            "nvidia-smi",
            "--query-gpu=index,name,memory.total",
            "--format=csv,noheader,nounits",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        log.debug("nvidia-smi exited with code %s", result.returncode)
        return 0, ()
    vram: list[int] = []
    for line in result.stdout.strip().splitlines():
        if not line.strip():
            continue
        vram_bytes = _parse_vram_line(line)
        if vram_bytes is None:
            log.debug("Skipping unparseable nvidia-smi line: %r", line)
            continue
        vram.append(vram_bytes)
    return len(vram), tuple(vram)


def probe_system() -> SystemSpec:
    gpu_count, vram_bytes = _probe_gpus()
    cpu_physical, cpu_logical = _probe_cpu_counts()
    return SystemSpec(
        gpu_count=gpu_count,
        vram_bytes=vram_bytes,
        system_ram_bytes=_probe_system_ram_bytes(),
        cpu_physical=cpu_physical,
        cpu_logical=cpu_logical,
    )
