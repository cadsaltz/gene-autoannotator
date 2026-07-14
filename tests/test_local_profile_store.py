import json
import re
from pathlib import Path

import pytest

from coordinator.profile_store import (
    DuplicateProfileError,
    InvalidProfileError,
    LocalProfileStore,
    profile_store_from_env,
)


def user_profile_payload(**overrides):
    payload = {
        "profile_id": "user-tcruzi",
        "canonical_name": "Trypanosoma cruzi custom",
        "species_name": "Trypanosoma cruzi",
        "strain": "Custom",
        "synonyms": ["custom t cruzi"],
        "species_synonyms": ["T. cruzi"],
        "strain_synonyms": ["custom"],
        "locus_regex": r"^TcCUSTOM_\d+$",
        "search_terms": ["Trypanosoma cruzi", "T. cruzi"],
        "target_patterns": [r"Trypanosoma\scruzi"],
        "off_target_patterns": [r"Trypanosoma\sbrucei"],
        "excluded_species_patterns": [r"Trypanosoma\sbrucei"],
    }
    payload.update(overrides)
    return payload


def test_profile_store_from_env_uses_local_directory(tmp_path, monkeypatch):
    profiles_dir = tmp_path / "profiles"
    monkeypatch.setenv("PROFILES_DIR", str(profiles_dir))
    monkeypatch.delenv("MONGO_URI", raising=False)
    monkeypatch.delenv("MONGODB_URI", raising=False)

    store = profile_store_from_env()

    assert isinstance(store, LocalProfileStore)
    assert store.health()["status"] == "ok"
    assert profiles_dir.is_dir()
    by_id = {profile["profile_id"]: profile for profile in store.list_profiles()}
    assert "mtb-h37rv" in by_id
    assert "source" not in by_id["mtb-h37rv"]


def test_local_store_seeds_builtin_profiles_once(tmp_path):
    store = LocalProfileStore(tmp_path)
    first = {p["profile_id"] for p in store.list_profiles()}
    assert "mtb-h37rv" in first

    store.delete_profile("mtb-h37rv")
    assert store.get_profile("mtb-h37rv") is None

    # Re-open same directory: deleted seed must not come back.
    reopened = LocalProfileStore(tmp_path)
    assert reopened.get_profile("mtb-h37rv") is None
    assert "mtb-h37rv" not in {
        p["profile_id"] for p in reopened.list_profiles()
    }


def test_local_store_create_update_delete_round_trip(tmp_path):
    store = LocalProfileStore(tmp_path)
    created = store.create_profile(user_profile_payload())

    assert created["canonical_name"] == "Trypanosoma cruzi custom"
    assert "source" not in created
    assert (tmp_path / "user-tcruzi.json").is_file()

    updated = store.update_profile(
        "user-tcruzi",
        user_profile_payload(canonical_name="Trypanosoma cruzi edited"),
    )
    assert updated["canonical_name"] == "Trypanosoma cruzi edited"
    assert store.delete_profile("user-tcruzi") is True
    assert store.get_profile("user-tcruzi") is None
    assert not (tmp_path / "user-tcruzi.json").exists()


def test_local_store_persists_json_document(tmp_path):
    store = LocalProfileStore(tmp_path)
    store.create_profile(user_profile_payload(profile_id="persist-me"))

    raw = json.loads((tmp_path / "persist-me.json").read_text(encoding="utf-8"))
    assert raw["profile_id"] == "persist-me"
    assert "source" not in raw
    assert "trusted" not in raw
    assert "read_only" not in raw


def test_local_store_rejects_duplicate_profile_id(tmp_path):
    store = LocalProfileStore(tmp_path)
    with pytest.raises(DuplicateProfileError):
        store.create_profile(user_profile_payload(profile_id="mtb-h37rv"))


def test_local_store_updates_seeded_profile_in_place(tmp_path):
    store = LocalProfileStore(tmp_path)
    updated = store.update_profile(
        "mtb-h37rv",
        user_profile_payload(
            profile_id="mtb-h37rv",
            canonical_name="Mycobacterium tuberculosis H37Rv edited",
            species_name="Mycobacterium tuberculosis",
            locus_regex=r"^Rv\d{4}[Ac]?$",
        ),
    )
    assert updated["canonical_name"] == "Mycobacterium tuberculosis H37Rv edited"
    assert "source" not in updated
    disk = json.loads((tmp_path / "mtb-h37rv.json").read_text(encoding="utf-8"))
    assert disk["canonical_name"] == "Mycobacterium tuberculosis H37Rv edited"


def test_local_store_validates_locus_regex(tmp_path):
    store = LocalProfileStore(tmp_path)
    with pytest.raises(InvalidProfileError):
        store.create_profile(user_profile_payload(locus_regex="["))


def test_local_store_defaults_target_patterns_when_omitted(tmp_path):
    store = LocalProfileStore(tmp_path)
    payload = user_profile_payload(profile_id="user-default-patterns")
    payload.pop("target_patterns")

    created = store.create_profile(payload)

    assert created["target_patterns"] == [
        re.escape("Trypanosoma cruzi"),
        re.escape("Trypanosoma cruzi custom"),
        re.escape("T. cruzi"),
    ]


def test_local_store_persists_custom_fields_and_kegg_code(tmp_path):
    store = LocalProfileStore(tmp_path)
    created = store.create_profile({
        **user_profile_payload(profile_id="user-custom-fields"),
        "kegg_organism_code": "msm",
        "custom_fields": [{
            "key": "virulence_factor",
            "label": "Virulence factor",
            "description": "Contribution to virulence.",
            "type": "string",
            "required": False,
            "inference_strategy": "paper_llm",
            "ortholog_allowed": True,
        }],
    })

    assert created["kegg_organism_code"] == "msm"
    assert created["custom_fields"][0]["ortholog_allowed"] is True
