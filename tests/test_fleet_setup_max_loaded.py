def test_job_keep_alive_for_tier():
    from worker.bench import _job_keep_alive_for_tier

    assert _job_keep_alive_for_tier("warm_stack") == "5m"
    assert _job_keep_alive_for_tier("vram_overflow") == "0"
    assert _job_keep_alive_for_tier("swap") == "0"
    assert _job_keep_alive_for_tier("vram_overflow", cli_value="10m") == "10m"
