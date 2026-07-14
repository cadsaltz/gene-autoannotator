"""Additional LocalProfileStore validation coverage."""

import pytest

from coordinator.profile_store import InvalidProfileError, LocalProfileStore
from coordinator.schemas import ProfilesResponse


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


@pytest.mark.parametrize(
    "field",
    [
        "target_patterns",
        "off_target_patterns",
        "excluded_species_patterns",
    ],
)
def test_profile_store_validates_pattern_regex_lists(tmp_path, field):
    store = LocalProfileStore(tmp_path)

    with pytest.raises(InvalidProfileError):
        store.create_profile(user_profile_payload(**{field: [r"valid", "["]}))


def test_profile_store_preserves_explicit_target_patterns(tmp_path):
    store = LocalProfileStore(tmp_path)

    created = store.create_profile(
        user_profile_payload(
            profile_id="user-explicit-patterns",
            target_patterns=[r"Custom\s+target"],
        )
    )

    assert created["target_patterns"] == [r"Custom\s+target"]


def test_profile_store_detail_response_accepts_profile_without_locus_regex(tmp_path):
    store = LocalProfileStore(tmp_path)
    store.create_profile(
        user_profile_payload(profile_id="user-flexible", locus_regex=None)
    )

    response = ProfilesResponse(profiles=store.list_profiles())
    by_id = {profile.profile_id: profile for profile in response.profiles}

    assert by_id["user-flexible"].locus_regex is None


def test_profile_store_rejects_ortholog_allowed_without_kegg_code(tmp_path):
    store = LocalProfileStore(tmp_path)

    with pytest.raises(InvalidProfileError, match="ortholog_allowed requires kegg_organism_code"):
        store.create_profile({
            **user_profile_payload(profile_id="user-no-kegg"),
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
