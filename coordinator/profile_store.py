import os
import re
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

from autoannotation import field_defs
from autoannotation import organisms


PROFILE_DATABASE_NAME = "gene_autoannotator"
PROFILE_COLLECTION_NAME = "profiles"

PROFILE_ARRAY_FIELDS = (
    "synonyms",
    "species_synonyms",
    "strain_synonyms",
    "search_terms",
    "target_patterns",
    "off_target_patterns",
    "excluded_species_patterns",
)

PROFILE_REGEX_FIELDS = (
    "target_patterns",
    "off_target_patterns",
    "excluded_species_patterns",
)


class ProfileStoreUnavailable(RuntimeError):
    """Raised when user profile storage is not configured or reachable."""


class DuplicateProfileError(ValueError):
    """Raised when a profile id already exists."""


class InvalidProfileError(ValueError):
    """Raised when a profile payload cannot be stored."""


def _now_iso():
    return datetime.now(UTC).isoformat()


def _copy_document(document):
    copied = dict(document)
    for field in PROFILE_ARRAY_FIELDS:
        copied[field] = list(copied.get(field) or [])
    copied['custom_fields'] = list(copied.get('custom_fields') or copied.get('annotation_fields') or [])
    copied['annotation_fields'] = list(copied['custom_fields'])
    copied['default_field_ortholog'] = dict(copied.get('default_field_ortholog') or {})
    return copied


def _serialize_custom_fields(profile):
    custom = getattr(profile, 'custom_fields', ()) or ()
    return [
        field_def.to_dict() if hasattr(field_def, 'to_dict') else dict(field_def)
        for field_def in custom
    ]


def _normalize_custom_fields_payload(payload, kegg_code):
    raw = payload.get('custom_fields')
    if raw is None:
        raw = payload.get('annotation_fields') or []
    if not isinstance(raw, list):
        raise InvalidProfileError('custom_fields must be a list')
    default_keys = {item.key for item in field_defs.REQUIRED_DEFAULT_FIELDS}
    parsed = []
    for item in raw:
        if not isinstance(item, dict):
            raise InvalidProfileError('each custom field must be an object')
        field_def = field_defs.AnnotationFieldDef.from_mapping(item)
        if field_def.key in default_keys:
            raise InvalidProfileError(
                f'cannot override required default field {field_def.key!r}'
            )
        if field_def.ortholog_allowed and not kegg_code:
            raise InvalidProfileError(
                f'ortholog_allowed requires kegg_organism_code (field {field_def.key!r})'
            )
        parsed.append(field_def)
    field_defs.validate_custom_fields(tuple(parsed))
    adjusted = field_defs.apply_ortholog_policy(
        field_defs.REQUIRED_DEFAULT_FIELDS + tuple(parsed),
        kegg_code,
    )
    return [
        field_def.to_dict()
        for field_def in adjusted
        if field_def.key not in default_keys
    ]


def _normalize_default_field_ortholog_payload(payload, kegg_code):
    try:
        settings = field_defs.default_field_ortholog_from_mapping(payload)
    except ValueError as exc:
        raise InvalidProfileError(str(exc)) from exc
    if not kegg_code:
        settings = {key: False for key in settings}
    for key, enabled in settings.items():
        if enabled and not kegg_code:
            raise InvalidProfileError(
                f'ortholog_allowed requires kegg_organism_code (default field {key!r})'
            )
    base = {field.key: field.ortholog_allowed for field in field_defs.REQUIRED_DEFAULT_FIELDS}
    base.update(settings)
    return base


def _serialize_default_field_ortholog(profile):
    base = {field.key: field.ortholog_allowed for field in field_defs.REQUIRED_DEFAULT_FIELDS}
    raw = getattr(profile, 'default_field_ortholog', ()) or ()
    if isinstance(raw, dict):
        base.update({key: bool(value) for key, value in raw.items()})
    else:
        base.update({key: bool(value) for key, value in raw})
    return base


def _profile_to_document(profile, source="builtin", trusted=True, read_only=False):
    document = asdict(profile)
    for field in PROFILE_ARRAY_FIELDS:
        document[field] = list(document.get(field) or [])
    custom_fields = _serialize_custom_fields(profile)
    document['custom_fields'] = custom_fields
    document['annotation_fields'] = custom_fields
    document['default_field_ortholog'] = _serialize_default_field_ortholog(profile)
    document.pop('annotation_table_path', None)
    document.pop('annotation_id_column', None)
    document.pop('annotation_name_column', None)
    document.pop('annotation_feature_column', None)
    document.pop('annotation_feature_value', None)
    document["source"] = source
    document["trusted"] = trusted
    document["read_only"] = read_only
    return document


def _required_text(payload, field):
    value = payload.get(field)
    if value is None:
        raise InvalidProfileError(f"{field} is required")
    value = str(value).strip()
    if not value:
        raise InvalidProfileError(f"{field} is required")
    return value


def _optional_text(payload, field):
    value = payload.get(field)
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _list_field(payload, field):
    values = payload.get(field) or []
    if not isinstance(values, (list, tuple)):
        raise InvalidProfileError(f"{field} must be a list")
    return [str(value).strip() for value in values if str(value).strip()]


def _validate_regex(value, field):
    try:
        re.compile(value)
    except re.error as exc:
        raise InvalidProfileError(f"invalid {field}: {exc}") from exc


def _default_target_patterns(document):
    candidates = [
        document["species_name"],
        document["canonical_name"],
        *document.get("species_synonyms", []),
    ]
    seen = set()
    patterns = []
    for candidate in candidates:
        normalized = " ".join(str(candidate).split())
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        patterns.append(re.escape(normalized))
    return patterns


def _ensure_profile_id_matches(profile_id, payload):
    payload_profile_id = payload.get("profile_id")
    if payload_profile_id is None:
        return
    if str(payload_profile_id).strip() != profile_id:
        raise InvalidProfileError("profile_id cannot be changed")


def _normalize_profile_payload(payload):
    profile_id = _required_text(payload, "profile_id")
    canonical_name = _required_text(payload, "canonical_name")
    species_name = _required_text(payload, "species_name")
    locus_regex = _optional_text(payload, "locus_regex")
    if locus_regex is not None:
        _validate_regex(locus_regex, "locus_regex")

    now = _now_iso()
    document: dict[str, Any] = {
        "_id": profile_id,
        "profile_id": profile_id,
        "canonical_name": canonical_name,
        "species_name": species_name,
        "strain": _optional_text(payload, "strain"),
        "locus_regex": locus_regex,
        "source": "user",
        "trusted": bool(payload.get("trusted", False)),
        "read_only": bool(payload.get("read_only", False)),
        "created_at": now,
        "updated_at": now,
    }
    for field in PROFILE_ARRAY_FIELDS:
        document[field] = _list_field(payload, field)
    document['kegg_organism_code'] = _optional_text(payload, 'kegg_organism_code')
    document['custom_fields'] = _normalize_custom_fields_payload(
        payload,
        document['kegg_organism_code'],
    )
    document['annotation_fields'] = list(document['custom_fields'])
    document['default_field_ortholog'] = _normalize_default_field_ortholog_payload(
        payload,
        document['kegg_organism_code'],
    )
    if not document["target_patterns"]:
        document["target_patterns"] = _default_target_patterns(document)
    if payload.get("source"):
        document["source"] = _required_text(payload, "source")
    if payload.get("trusted") is not None:
        document["trusted"] = bool(payload.get("trusted"))
    if payload.get("read_only") is not None:
        document["read_only"] = bool(payload.get("read_only"))
    for field in PROFILE_REGEX_FIELDS:
        for pattern in document[field]:
            _validate_regex(pattern, field)
    return document


class InMemoryUserProfileStore:
    def __init__(self):
        self._documents: dict[str, dict[str, Any]] = {}

    def health(self):
        return {"status": "ok"}

    def list_profiles(self):
        return [_copy_document(document) for document in self._documents.values()]

    def get_profile(self, profile_id):
        document = self._documents.get(profile_id)
        if document is None:
            return None
        return _copy_document(document)

    def create_profile(self, payload):
        document = _normalize_profile_payload(payload)
        profile_id = document["profile_id"]
        if profile_id in self._documents:
            raise DuplicateProfileError(f"profile already exists: {profile_id}")
        self._documents[profile_id] = document
        return _copy_document(document)

    def update_profile(self, profile_id, payload):
        existing = self._documents.get(profile_id)
        if existing is None:
            return None
        _ensure_profile_id_matches(profile_id, payload)
        document = _normalize_profile_payload(payload)
        document["created_at"] = existing["created_at"]
        document["updated_at"] = _now_iso()
        self._documents[profile_id] = document
        return _copy_document(document)

    def delete_profile(self, profile_id):
        return self._documents.pop(profile_id, None) is not None


class DisabledUserProfileStore:
    def health(self):
        return {"status": "unconfigured", "message": "MONGO_URI is not set"}

    def _raise(self):
        raise ProfileStoreUnavailable("MONGO_URI is not configured")

    def list_profiles(self):
        return []

    def get_profile(self, profile_id):
        return None

    def create_profile(self, payload):
        self._raise()

    def update_profile(self, profile_id, payload):
        self._raise()

    def delete_profile(self, profile_id):
        self._raise()


class MongoUserProfileStore:
    def __init__(
        self,
        mongo_uri,
        *,
        database_name=PROFILE_DATABASE_NAME,
        collection_name=PROFILE_COLLECTION_NAME,
    ):
        self.mongo_uri = mongo_uri
        self.database_name = database_name
        self.collection_name = collection_name
        self._client = None
        self._collection = None

    def _get_collection(self):
        if self._collection is None:
            try:
                from pymongo import MongoClient
            except ImportError as exc:
                raise ProfileStoreUnavailable(
                    "pymongo is required for MongoDB profile storage"
                ) from exc
            self._client = MongoClient(self.mongo_uri, serverSelectionTimeoutMS=1000)
            self._collection = self._client[self.database_name][self.collection_name]
        return self._collection

    def health(self):
        try:
            self._get_collection().database.client.admin.command("ping")
        except Exception as exc:  # noqa: BLE001 - health reports storage failures.
            return {"status": "unavailable", "message": str(exc)}
        return {"status": "ok", "database": self.database_name}

    def list_profiles(self):
        return list(self._get_collection().find({}, {"_id": 0}).sort("profile_id", 1))

    def get_profile(self, profile_id):
        return self._get_collection().find_one({"profile_id": profile_id}, {"_id": 0})

    def create_profile(self, payload):
        document = _normalize_profile_payload(payload)
        existing = self.get_profile(document["profile_id"])
        if existing is not None:
            raise DuplicateProfileError(document["profile_id"])
        self._get_collection().insert_one(document)
        document.pop("_id", None)
        return document

    def update_profile(self, profile_id, payload):
        existing = self.get_profile(profile_id)
        if existing is None:
            return None
        _ensure_profile_id_matches(profile_id, payload)
        document = _normalize_profile_payload({**payload, "profile_id": profile_id})
        document.pop("_id", None)
        document["created_at"] = existing.get("created_at")
        self._get_collection().update_one(
            {"profile_id": profile_id},
            {"$set": document},
        )
        return document

    def delete_profile(self, profile_id):
        result = self._get_collection().delete_one({"profile_id": profile_id})
        return result.deleted_count == 1


def user_profile_store_from_env():
    mongo_uri = os.getenv("MONGO_URI") or os.getenv("MONGODB_URI")
    if not mongo_uri:
        return DisabledUserProfileStore()
    return MongoUserProfileStore(mongo_uri)


class BuiltinAndUserProfileStore:
    def __init__(self, user_store=None, profiles=organisms.PROFILES):
        self.user_store = user_store or DisabledUserProfileStore()
        self._builtin_profiles = {
            profile.profile_id: _profile_to_document(profile)
            for profile in profiles
        }

    def health(self):
        return {
            "status": "ok",
            "user_profiles": self.user_store.health(),
        }

    def list_profiles(self):
        profiles_by_id = {
            profile_id: _copy_document(profile)
            for profile_id, profile in self._builtin_profiles.items()
        }
        for profile in self.user_store.list_profiles():
            profiles_by_id[profile["profile_id"]] = _copy_document(profile)
        return list(profiles_by_id.values())

    def get_profile(self, profile_id):
        user_profile = self.user_store.get_profile(profile_id)
        if user_profile is not None:
            return _copy_document(user_profile)
        builtin = self._builtin_profiles.get(profile_id)
        if builtin is not None:
            return _copy_document(builtin)
        return None

    def create_user_profile(self, payload):
        profile_id = _required_text(payload, "profile_id")
        if profile_id in self._builtin_profiles:
            raise DuplicateProfileError(f"profile already exists: {profile_id}")
        return self.user_store.create_profile(payload)

    def update_user_profile(self, profile_id, payload):
        _ensure_profile_id_matches(profile_id, payload)
        if profile_id in self._builtin_profiles:
            override_payload = {
                **payload,
                "profile_id": profile_id,
                "source": "builtin",
                "trusted": True,
                "read_only": False,
            }
            existing = self.user_store.get_profile(profile_id)
            if existing is None:
                return self.user_store.create_profile(override_payload)
            return self.user_store.update_profile(profile_id, override_payload)
        return self.user_store.update_profile(profile_id, payload)

    def delete_user_profile(self, profile_id):
        if profile_id in self._builtin_profiles:
            if self.user_store.get_profile(profile_id) is None:
                return False
            return self.user_store.delete_profile(profile_id)
        return self.user_store.delete_profile(profile_id)
