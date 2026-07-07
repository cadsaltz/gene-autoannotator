import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

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


def _healthy_response() -> dict:
    return {
        "status": "ok",
        "workers": {"connected": 1, "total_slots": 4},
        "stores": {"annotations": {"status": "ok"}},
    }


def _client_with_transport(handler):
    transport = httpx.MockTransport(handler)
    return httpx.Client(base_url="http://coordinator.test", transport=transport)


def _patch_preflight_client(handler):
    transport = httpx.MockTransport(handler)
    real_client = httpx.Client

    def client_factory(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    return patch.object(pm.httpx, "Client", side_effect=client_factory)


def test_preflight_ok():
    def handler(request):
        assert request.url.path == "/health"
        assert request.headers["authorization"] == "Bearer secret-token"
        return httpx.Response(200, json=_healthy_response())

    with _patch_preflight_client(handler):
        health = pm.preflight("http://coordinator.test", "secret-token")
    assert health["status"] == "ok"


def test_preflight_raises_on_no_workers():
    def handler(request):
        health = _healthy_response()
        health["workers"]["connected"] = 0
        return httpx.Response(200, json=health)

    with _patch_preflight_client(handler):
        with pytest.raises(RuntimeError, match="No workers connected"):
            pm.preflight("http://coordinator.test", "")


def test_preflight_raises_on_zero_slots():
    def handler(request):
        health = _healthy_response()
        health["workers"]["total_slots"] = 0
        return httpx.Response(200, json=health)

    with _patch_preflight_client(handler):
        with pytest.raises(RuntimeError, match="0 slots"):
            pm.preflight("http://coordinator.test", "")


def test_preflight_raises_on_unhealthy_coordinator():
    def handler(request):
        return httpx.Response(200, json={"status": "degraded"})

    with _patch_preflight_client(handler):
        with pytest.raises(RuntimeError, match="Coordinator unhealthy"):
            pm.preflight("http://coordinator.test", "")


def test_preflight_raises_on_mongo_unavailable():
    def handler(request):
        health = _healthy_response()
        health["stores"]["annotations"]["status"] = "unavailable"
        return httpx.Response(200, json=health)

    with _patch_preflight_client(handler):
        with pytest.raises(RuntimeError, match="Mongo annotation store unavailable"):
            pm.preflight("http://coordinator.test", "")


def test_submit_job_payload():
    captured: dict = {}

    def handler(request):
        assert request.method == "POST"
        assert request.url.path == "/jobs"
        captured["payload"] = json.loads(request.content.decode())
        return httpx.Response(201, json={"job_id": "job-123", "status": "queued"})

    client = _client_with_transport(handler)
    job_id = pm.submit_job(client, profile="mtb-h37rv", locus="Rv0001")
    assert job_id == "job-123"
    assert captured["payload"] == {
        "profile": "mtb-h37rv",
        "locus": "Rv0001",
        "allow_online_name_lookup": False,
        "allow_ortholog_fallback": True,
    }


def test_poll_job_returns_on_completion():
    poll_count = {"n": 0}

    def handler(request):
        poll_count["n"] += 1
        status = "running" if poll_count["n"] == 1 else "completed"
        return httpx.Response(200, json={"id": "job-123", "status": status})

    client = _client_with_transport(handler)
    with patch.object(pm.time, "sleep"):
        job = pm.poll_job(client, "job-123", poll_interval=0.01)
    assert job["status"] == "completed"
    assert poll_count["n"] == 2


def test_verify_annotation_saved_found():
    def handler(request):
        assert request.url.path == "/annotations/mtb-h37rv:Rv0001"
        return httpx.Response(200, json={"id": "mtb-h37rv:Rv0001", "locus": "Rv0001"})

    client = _client_with_transport(handler)
    annotation = pm.verify_annotation_saved(client, "mtb-h37rv", "Rv0001")
    assert annotation == {"id": "mtb-h37rv:Rv0001", "locus": "Rv0001"}


def test_verify_annotation_saved_missing():
    def handler(request):
        return httpx.Response(404)

    client = _client_with_transport(handler)
    assert pm.verify_annotation_saved(client, "mtb-h37rv", "Rv0001") is None


def _memory_samples(*used_gib: float) -> list[dict]:
    return [
        {"timestamp": f"t{i}", "used_bytes": int(gib * pm.GIB)}
        for i, gib in enumerate(used_gib)
    ]


def _completed_job(*, ortholog_ran: bool | None = True) -> dict:
    job: dict = {"id": "job-abc", "status": "completed"}
    if ortholog_ran is not None:
        job["result"] = {
            "annotation": {
                "annotation_metadata": {"ortholog_pass": {"ran": ortholog_ran}}
            }
        }
    return job


def test_build_report():
    baseline = 40.0
    samples = _memory_samples(baseline, baseline, baseline + 10, baseline + 21)
    report = pm.build_report(
        samples=samples,
        baseline_samples=2,
        job=_completed_job(ortholog_ran=True),
        safety_factor=0.20,
        profile="mtb-h37rv",
        locus="Rv1734c",
    )
    assert report["profile"] == "mtb-h37rv"
    assert report["locus"] == "Rv1734c"
    assert report["job_id"] == "job-abc"
    assert report["job_status"] == "completed"
    assert report["ortholog_pass_ran"] is True
    assert report["sample_count"] == 4
    assert report["baseline_used_bytes"] == int(baseline * pm.GIB)
    assert report["incremental_used_bytes"]["min"] == 0
    assert report["incremental_used_bytes"]["max"] == int(21 * pm.GIB)
    assert report["peak_incremental_bytes"] == int(21 * pm.GIB)
    assert report["recommended_job_memory_gb"] == 26


def test_build_report_ortholog_pass_missing():
    report = pm.build_report(
        samples=_memory_samples(40, 40, 50),
        baseline_samples=2,
        job={"id": "job-x", "status": "completed"},
        safety_factor=0.20,
        profile="mtb-h37rv",
        locus="Rv0001",
    )
    assert report["ortholog_pass_ran"] is None


def test_build_report_raises_on_insufficient_samples():
    with pytest.raises(RuntimeError, match="Not enough memory samples"):
        pm.build_report(
            samples=_memory_samples(40),
            baseline_samples=2,
            job=_completed_job(),
            safety_factor=0.20,
            profile="mtb-h37rv",
            locus="Rv1734c",
        )


def test_format_report_text():
    report = pm.build_report(
        samples=_memory_samples(40, 40, 50, 61.6),
        baseline_samples=2,
        job=_completed_job(ortholog_ran=True),
        safety_factor=0.20,
        profile="mtb-h37rv",
        locus="Rv1734c",
    )
    text = pm.format_report_text(report)
    assert "Gene Autoannotator — Observational Job Memory Profile" in text
    assert "mtb-h37rv / Rv1734c" in text
    assert "job-abc" in text
    assert "Ortholog pass ran:True" in text
    assert "Recommended job allocation: 26 GB" in text
    assert "← peak" in text
