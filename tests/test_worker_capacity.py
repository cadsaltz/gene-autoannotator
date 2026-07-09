from worker import capacity
from worker.fleet.config import FleetConfig


def test_slots_from_budget():
    assert capacity.compute_slots(42, job_estimate_gb=20, headroom_gb=4) == 1
    assert capacity.compute_slots(200, job_estimate_gb=20, headroom_gb=4) == 9
    assert capacity.compute_slots(64, job_estimate_gb=20, headroom_gb=4) == 3
    assert capacity.compute_slots(10, job_estimate_gb=20, headroom_gb=4) == 0


def test_admission_gate():
    gib = 1024 ** 3
    assert capacity.can_admit(3 * gib) is True
    assert capacity.can_admit(1 * gib) is False


def test_compute_slots_from_fleet():
    fleet = FleetConfig(num_servers=2, parallel=2, max_slots=5)
    assert capacity.compute_slots_from_fleet(fleet) == 5
