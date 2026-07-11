from dataclasses import dataclass
from typing import Literal


MemoryTier = Literal["warm_stack", "swap", "vram_overflow"]


@dataclass(frozen=True)
class FleetConfig:
    num_servers: int
    parallel: int
    max_slots: int
    base_port: int = 11434
    keep_alive: str = "5m"
    w_all_bytes: int = 0
    w_peak_bytes: int = 0
    c_slot_bytes: int = 0
    memory_tier: MemoryTier = "warm_stack"
    model_count: int = 0

    @property
    def lanes_per_server(self) -> int:
        """Concurrent router lanes per Ollama server (parallel × model lanes)."""
        models = self.model_count if self.model_count > 0 else 1
        return self.parallel * models

    @property
    def agg_lanes(self) -> int:
        return self.num_servers * self.lanes_per_server

    def backend_hosts(self) -> list[str]:
        return [f"http://127.0.0.1:{self.base_port + i}" for i in range(self.num_servers)]
