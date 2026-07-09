from __future__ import annotations

import dataclasses
import shutil
import subprocess
from typing import List

import psutil


@dataclasses.dataclass(frozen=True)
class SystemSpec:
    gpu_count: int
    vram_bytes: List[int]
    system_ram_bytes: int
    cpu_physical: int
    cpu_logical: int

    @property
    def vram_total_bytes(self) -> int:
        return sum(self.vram_bytes)


def _probe_gpus() -> tuple[int, list[int]]:
    if shutil.which("nvidia-smi") is None:
        return 0, []
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
        return 0, []
    vram = []
    for line in result.stdout.strip().splitlines():
        if not line.strip():
            continue
        parts = [part.strip() for part in line.split(",")]
        if len(parts) >= 3:
            vram.append(int(float(parts[2]) * 1024 * 1024))
    return len(vram), vram


def probe_system() -> SystemSpec:
    gpu_count, vram_bytes = _probe_gpus()
    mem = psutil.virtual_memory()
    return SystemSpec(
        gpu_count=gpu_count,
        vram_bytes=vram_bytes,
        system_ram_bytes=int(mem.total),
        cpu_physical=psutil.cpu_count(logical=False) or 1,
        cpu_logical=psutil.cpu_count(logical=True) or 1,
    )
