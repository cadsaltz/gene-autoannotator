from shared.job_contract import AnnotationJobRequest, OrthologOverride


def test_job_request_round_trips_from_shared():
    request = AnnotationJobRequest(profile="mtb-h37rv", locus="Rv0001")
    dumped = request.model_dump()
    assert dumped["profile"] == "mtb-h37rv"
    assert dumped["locus"] == "Rv0001"
    assert AnnotationJobRequest(**dumped).locus == "Rv0001"


def test_job_request_requires_profile_or_organism():
    import pytest

    with pytest.raises(ValueError):
        AnnotationJobRequest(locus="Rv0001")


def test_ortholog_override_requires_fallback_enabled():
    import pytest

    with pytest.raises(ValueError):
        AnnotationJobRequest(
            profile="mtb-h37rv",
            locus="Rv0001",
            ortholog_override=OrthologOverride(profile_id="mtb-h37rv", locus="Rv0002"),
        )


def test_coordinator_schemas_reexports_job_request():
    from coordinator.schemas import AnnotationJobRequest as CoordJobRequest

    assert CoordJobRequest is AnnotationJobRequest


def test_worker_contract_models_validate():
    from shared.worker_contract import (
        ClaimResponse,
        JobComplete,
        WorkerHeartbeat,
        WorkerRegister,
    )
    from shared.job_contract import AnnotationJobRequest

    register = WorkerRegister(
        worker_name="laptop-a",
        hostname="laptop-a",
        agent_version="0.1.0",
        total_memory_bytes=64_000_000_000,
        dedicated_memory_bytes=42_000_000_000,
        max_slots=2,
        ollama_models=["llama3:8b"],
    )
    assert register.max_slots == 2

    heartbeat = WorkerHeartbeat(
        active_jobs=1, free_slots=1, memory_available_bytes=10_000_000_000, cpu_percent=12.5
    )
    assert heartbeat.state == "ready"

    claim = ClaimResponse(
        job_id="j1",
        request=AnnotationJobRequest(profile="mtb-h37rv", locus="Rv0001"),
        lease_expires_at="2026-07-03T00:00:00+00:00",
    )
    assert claim.request.locus == "Rv0001"
    assert JobComplete(result={"annotation": {}}).result == {"annotation": {}}
