from backend.access import BOOTSTRAP_ADMIN_EMAIL
from backend.annotation_store import InMemoryAnnotationStore

from tests.auth_helpers import make_client, second_client, sign_in


def _completed_job(job_id, generated_at):
    return {
        "id": job_id,
        "request": {"organism": "Custom bacterium", "name": "abc1"},
        "output_path": f"/srv/outputs/{job_id}/gen_abc1.json",
        "result": {
            "annotation": {
                "gene_id": None,
                "name": "abc1",
                "annotation_metadata": {
                    "generated_at": generated_at,
                    "profile_id": "ad-hoc-custom-bacterium",
                    "canonical_name": "Custom bacterium",
                    "species_name": "Custom bacterium",
                    "strain": None,
                    "resolved_locus": None,
                    "resolved_name": "abc1",
                    "profile_source": "ad_hoc",
                },
            }
        },
        "finished_at": generated_at,
    }


def _clients_with_two_versions(tmp_path):
    store = InMemoryAnnotationStore()
    store.save_completed_job(_completed_job("job-old", "2026-01-01T00:00:00Z"))
    annotation_id = store.save_completed_job(_completed_job("job-new", "2026-02-01T00:00:00Z"))
    user = sign_in(make_client(tmp_path, annotation_store=store))
    admin = second_client(user, BOOTSTRAP_ADMIN_EMAIL)
    return user, admin, annotation_id


def test_annotation_detail_hides_job_id_and_output_path_from_users(tmp_path):
    user, admin, annotation_id = _clients_with_two_versions(tmp_path)

    user_detail = user.get(f"/annotations/{annotation_id}").json()
    admin_detail = admin.get(f"/annotations/{annotation_id}").json()

    assert user_detail["result"]["annotation"]["name"] == "abc1"
    assert user_detail.get("job_id") is None
    assert user_detail.get("output_path") is None
    assert admin_detail["job_id"] == "job-new"
    assert admin_detail["output_path"] == "/srv/outputs/job-new/gen_abc1.json"


def test_annotation_versions_hide_job_id_and_output_path_from_users(tmp_path):
    user, admin, annotation_id = _clients_with_two_versions(tmp_path)

    user_versions = user.get(f"/annotations/{annotation_id}/versions").json()["versions"]
    admin_versions = admin.get(f"/annotations/{annotation_id}/versions").json()["versions"]

    assert len(user_versions) == 1
    assert "job_id" not in user_versions[0]
    assert "output_path" not in user_versions[0]
    assert user_versions[0]["generated_at"] == "2026-01-01T00:00:00Z"
    assert admin_versions[0]["job_id"] == "job-old"
    assert admin_versions[0]["output_path"] == "/srv/outputs/job-old/gen_abc1.json"
