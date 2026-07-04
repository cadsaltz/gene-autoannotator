from shared.job_contract import AnnotationJobRequest
from worker import executor


def test_executor_calls_annotation_main_with_request_fields():
    captured = {}

    def fake_main(**kwargs):
        captured.update(kwargs)
        return {"annotation": {"gene_id": "Rv0001"}, "output_path": "gen_json/gen_Rv0001.json"}

    request = AnnotationJobRequest(profile="mtb-h37rv", locus="Rv0001", allow_online_name_lookup=False)
    result = executor.run_annotation_job(request, annotation_main=fake_main)

    assert captured["profile"] == "mtb-h37rv"
    assert captured["locus"] == "Rv0001"
    assert captured["no_online_name_lookup"] is True
    assert result["output_path"] == "gen_json/gen_Rv0001.json"
