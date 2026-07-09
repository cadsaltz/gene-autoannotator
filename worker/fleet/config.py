from dataclasses import dataclass


@dataclass(frozen=True)
class FleetConfig:
    num_servers: int
    parallel: int
    max_slots: int
    base_port: int = 11434
    keep_alive: str = "5m"
    w_all_bytes: int = 0
    c_slot_bytes: int = 0

    @property
    def agg_lanes(self) -> int:
        return self.num_servers * self.parallel

    def backend_hosts(self) -> list[str]:
        return [f"http://127.0.0.1:{self.base_port + i}" for i in range(self.num_servers)]
