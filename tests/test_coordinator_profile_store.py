import re

import pytest

from coordinator.profile_store import (
    BuiltinAndUserProfileStore,
    DisabledUserProfileStore,
    DuplicateProfileError,
    InMemoryUserProfileStore,
    InvalidProfileError,
    MongoUserProfileStore,
    user_profile_store_from_env,
)
from coordinator.schemas import ProfilesResponse


class FakeMongoCollection:
    def __init__(self, documents=None):
        self.documents = {
            document["profile_id"]: dict(document)
            for document in documents or []
        }
        self.update_calls = []

    def _project(self, document, projection):
        projected = dict(document)
        if projection and projection.get("_id") == 0:
            projected.pop("_id", None)
        return projected

    def find_one(self, filter, projection=None):
        document = self.documents.get(filter["profile_id"])
        if document is None:
            return None
        return self._project(document, projection)

    def insert_one(self, document):
        self.documents[document["profile_id"]] = dict(document)

    def update_one(self, filter, update):
        self.update_calls.append((filter, update))
        self.documents[filter["profile_id"]].update(update["$set"])

    def replace_one(self, filter, document):
        raise AssertionError("Mongo profile updates must not replace documents")


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


def test_profile_store_from_env_is_disabled_without_mongo(monkeypatch):
    monkeypatch.delenv("MONGO_URI", raising=False)
    monkeypatch.delenv("MONGODB_URI", raising=False)

    store = user_profile_store_from_env()

    assert isinstance(store, DisabledUserProfileStore)
    assert store.health()["status"] == "unconfigured"


def test_mongo_profile_store_create_returns_public_document_and_stores_document():
    collection = FakeMongoCollection()
    store = MongoUserProfileStore("mongodb://example")
    store._collection = collection

    created = store.create_profile(user_profile_payload())

    assert "_id" not in created
    stored = collection.documents["user-tcruzi"]
    assert stored["_id"] == "user-tcruzi"
    assert stored["canonical_name"] == "Trypanosoma cruzi custom"


def test_mongo_profile_store_update_preserves_mongo_id_and_created_at():
    collection = FakeMongoCollection([
        {
            "_id": "mongo-object-id",
            "profile_id": "user-tcruzi",
            "canonical_name": "Trypanosoma cruzi original",
            "species_name": "Trypanosoma cruzi",
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
        }
    ])
    store = MongoUserProfileStore("mongodb://example")
    store._collection = collection

    updated = store.update_profile(
        "user-tcruzi",
        user_profile_payload(canonical_name="Trypanosoma cruzi edited"),
    )

    assert "_id" not in updated
    assert updated["created_at"] == "2026-01-01T00:00:00+00:00"
    stored = collection.documents["user-tcruzi"]
    assert stored["_id"] == "mongo-object-id"
    assert stored["created_at"] == "2026-01-01T00:00:00+00:00"
    assert stored["canonical_name"] == "Trypanosoma cruzi edited"
    assert collection.update_calls
    update = collection.update_calls[0][1]
    assert "$set" in update
    assert "_id" not in update["$set"]


def test_mongo_profile_store_update_rejects_profile_id_mismatch():
    collection = FakeMongoCollection([
        {
            "_id": "mongo-object-id",
            "profile_id": "user-tcruzi",
            "canonical_name": "Trypanosoma cruzi original",
            "species_name": "Trypanosoma cruzi",
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
        }
    ])
    store = MongoUserProfileStore("mongodb://example")
    store._collection = collection

    with pytest.raises(InvalidProfileError):
        store.update_profile(
            "user-tcruzi",
            user_profile_payload(profile_id="different-profile"),
        )


def test_profile_store_lists_builtin_and_user_profiles():
    user_store = InMemoryUserProfileStore()
    user_store.create_profile(user_profile_payload())
    store = BuiltinAndUserProfileStore(user_store=user_store)

    profiles = store.list_profiles()
    by_id = {profile["profile_id"]: profile for profile in profiles}

    assert by_id["mtb-h37rv"]["source"] == "builtin"
    assert by_id["mtb-h37rv"]["read_only"] is False
    assert by_id["user-tcruzi"]["source"] == "user"
    assert by_id["user-tcruzi"]["trusted"] is False
    assert by_id["user-tcruzi"]["read_only"] is False


def test_profile_store_allows_builtin_update_as_override():
    store = BuiltinAndUserProfileStore(user_store=InMemoryUserProfileStore())

    updated = store.update_user_profile(
        "mtb-h37rv",
        user_profile_payload(
            profile_id="mtb-h37rv",
            canonical_name="Mycobacterium tuberculosis H37Rv edited",
            species_name="Mycobacterium tuberculosis",
            locus_regex=r"^Rv\d{4}[Ac]?$",
        ),
    )

    assert updated["canonical_name"] == "Mycobacterium tuberculosis H37Rv edited"
    assert updated["source"] == "builtin"
    assert updated["read_only"] is False
    listed = {profile["profile_id"]: profile for profile in store.list_profiles()}
    assert listed["mtb-h37rv"]["canonical_name"] == "Mycobacterium tuberculosis H37Rv edited"
    assert len(listed) == len(store._builtin_profiles) + 0  # no duplicate mtb entry


def test_profile_store_reset_builtin_deletes_override_only():
    store = BuiltinAndUserProfileStore(user_store=InMemoryUserProfileStore())
    store.update_user_profile(
        "mtb-h37rv",
        user_profile_payload(
            profile_id="mtb-h37rv",
            canonical_name="Edited MTB",
            species_name="Mycobacterium tuberculosis",
            locus_regex=r"^Rv\d{4}[Ac]?$",
        ),
    )

    assert store.delete_user_profile("mtb-h37rv") is True
    profile = store.get_profile("mtb-h37rv")
    assert profile["canonical_name"] == "Mycobacterium tuberculosis H37Rv"
    assert store.delete_user_profile("mtb-h37rv") is False


def test_profile_store_rejects_duplicate_builtin_profile_id():
    store = BuiltinAndUserProfileStore(user_store=InMemoryUserProfileStore())

    with pytest.raises(DuplicateProfileError):
        store.create_user_profile(user_profile_payload(profile_id="mtb-h37rv"))


def test_profile_store_validates_locus_regex():
    store = BuiltinAndUserProfileStore(user_store=InMemoryUserProfileStore())

    with pytest.raises(InvalidProfileError):
        store.create_user_profile(user_profile_payload(locus_regex="["))


@pytest.mark.parametrize(
    "field",
    [
        "target_patterns",
        "off_target_patterns",
        "excluded_species_patterns",
    ],
)
def test_profile_store_validates_pattern_regex_lists(field):
    store = BuiltinAndUserProfileStore(user_store=InMemoryUserProfileStore())

    with pytest.raises(InvalidProfileError):
        store.create_user_profile(user_profile_payload(**{field: [r"valid", "["]}))


def test_profile_store_saves_valid_pattern_regex_lists():
    store = BuiltinAndUserProfileStore(user_store=InMemoryUserProfileStore())

    created = store.create_user_profile(
        user_profile_payload(
            profile_id="user-valid-patterns",
            target_patterns=[r"Trypanosoma\scruzi", r"T\.\scruzi"],
            off_target_patterns=[r"Trypanosoma\sbrucei"],
            excluded_species_patterns=[r"Leishmania\smajor"],
        )
    )

    assert created["target_patterns"] == [r"Trypanosoma\scruzi", r"T\.\scruzi"]
    assert created["off_target_patterns"] == [r"Trypanosoma\sbrucei"]
    assert created["excluded_species_patterns"] == [r"Leishmania\smajor"]


def test_profile_store_defaults_target_patterns_when_omitted():
    store = BuiltinAndUserProfileStore(user_store=InMemoryUserProfileStore())
    payload = user_profile_payload(profile_id="user-default-patterns")
    payload.pop("target_patterns")

    created = store.create_user_profile(payload)

    assert created["target_patterns"] == [
        re.escape("Trypanosoma cruzi"),
        re.escape("Trypanosoma cruzi custom"),
        re.escape("T. cruzi"),
    ]


def test_profile_store_preserves_explicit_target_patterns():
    store = BuiltinAndUserProfileStore(user_store=InMemoryUserProfileStore())

    created = store.create_user_profile(
        user_profile_payload(
            profile_id="user-explicit-patterns",
            target_patterns=[r"Custom\s+target"],
        )
    )

    assert created["target_patterns"] == [r"Custom\s+target"]


def test_profile_store_detail_response_accepts_user_profile_without_locus_regex():
    store = BuiltinAndUserProfileStore(user_store=InMemoryUserProfileStore())
    store.create_user_profile(
        user_profile_payload(profile_id="user-flexible", locus_regex=None)
    )

    response = ProfilesResponse(profiles=store.list_profiles())
    by_id = {profile.profile_id: profile for profile in response.profiles}

    assert by_id["user-flexible"].locus_regex is None
    assert by_id["user-flexible"].source == "user"


def test_profile_store_updates_and_deletes_user_profile():
    store = BuiltinAndUserProfileStore(user_store=InMemoryUserProfileStore())
    store.create_user_profile(user_profile_payload())
    updated = store.update_user_profile(
        "user-tcruzi",
        user_profile_payload(canonical_name="Trypanosoma cruzi edited"),
    )

    assert updated["canonical_name"] == "Trypanosoma cruzi edited"
    assert store.delete_user_profile("user-tcruzi") is True
    assert store.get_profile("user-tcruzi") is None


def test_profile_store_persists_custom_fields_and_kegg_code():
    store = BuiltinAndUserProfileStore(user_store=InMemoryUserProfileStore())
    created = store.create_user_profile({
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
    assert created["custom_fields"][0]["key"] == "virulence_factor"
    assert created["custom_fields"][0]["ortholog_allowed"] is True


def test_profile_store_rejects_ortholog_allowed_without_kegg_code():
    store = BuiltinAndUserProfileStore(user_store=InMemoryUserProfileStore())

    with pytest.raises(InvalidProfileError, match="ortholog_allowed requires kegg_organism_code"):
        store.create_user_profile({
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
