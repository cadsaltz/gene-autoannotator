import importlib.util
import sys
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "profile_job_memory.py"
_spec = importlib.util.spec_from_file_location("profile_job_memory", _SCRIPT)
pm = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = pm
_spec.loader.exec_module(pm)


def test_parse_free_b_mem_line():
    sample = "Mem:  131805184  45634048  23456789  1234567  62714112  82123456"
    parsed = pm.parse_free_b_mem_line(sample)
    assert parsed == {
        "total_bytes": 131805184,
        "used_bytes": 45634048,
        "free_bytes": 23456789,
        "shared_bytes": 1234567,
        "buff_cache_bytes": 62714112,
        "available_bytes": 82123456,
    }


def test_summarize_used_bytes():
    samples = [
        {"elapsed_sec": 0.0, "used_bytes": 40 * pm.GIB},
        {"elapsed_sec": 1.0, "used_bytes": 50 * pm.GIB},
        {"elapsed_sec": 2.0, "used_bytes": 45 * pm.GIB},
    ]
    stats = pm.summarize_bytes([s["used_bytes"] for s in samples])
    assert stats["min"] == 40 * pm.GIB
    assert stats["max"] == 50 * pm.GIB
    assert stats["mean"] == 45 * pm.GIB


def test_recommend_job_memory_gb():
    peak_incremental = int(21.6 * pm.GIB)
    assert pm.recommend_job_memory_gb(peak_incremental, safety_factor=0.20) == 26


def test_parse_memory_log(tmp_path):
    log = tmp_path / "mem.log"
    log.write_text(
        "\n=== 2026-07-06T18:00:00+00:00 ===\n"
        "              total        used        free      shared  buff/cache   available\n"
        "Mem:  131805184  45634048  23456789  1234567  62714112  82123456\n"
        "              total        used        free      shared  buff/cache   available\n"
        "Mem:       125Gi        42Gi        21Gi       1Gi        61Gi        76Gi\n"
    )
    samples = pm.parse_memory_log(log)
    assert len(samples) == 1
    assert samples[0]["used_bytes"] == 45634048
