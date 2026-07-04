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
