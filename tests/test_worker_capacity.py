from worker import capacity


def test_slots_from_budget():
    assert capacity.compute_slots(42, job_estimate_gb=20, headroom_gb=4) == 1
    assert capacity.compute_slots(200, job_estimate_gb=20, headroom_gb=4) == 9
    assert capacity.compute_slots(64, job_estimate_gb=20, headroom_gb=4) == 3
    assert capacity.compute_slots(10, job_estimate_gb=20, headroom_gb=4) == 0


def test_admission_gate():
    gib = 1024 ** 3
    assert capacity.can_admit(30 * gib, job_estimate_gb=20, headroom_gb=4) is True
    assert capacity.can_admit(20 * gib, job_estimate_gb=20, headroom_gb=4) is False
