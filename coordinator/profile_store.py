import json
import os
import re
import shutil
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from autoannotation import field_defs
from autoannotation import organisms


DEFAULT_PROFILES_DIR = "data/profiles"
SEED_MARKER_NAME = ".seeded"

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

# Legacy Mongo/builtin keys dropped from local profile documents.
_LEGACY_METADATA_KEYS = ("source", "trusted", "read_only", "_id")


class ProfileStoreUnavailable(RuntimeError):
    """Raised when profile storage is not configured or reachable."""


class DuplicateProfileError(ValueError):
    """Raised when a profile id already exists."""


class InvalidProfileError(ValueError):
    """Raised when a profile payload cannot be stored."""


def _now_iso():
    return datetime.now(UTC).isoformat()


def _copy_document(document):
    copied = dict(document)
    for key in _LEGACY_METADATA_KEYS:
        copied.pop(key, None)
    for field in PROFILE_ARRAY_FIELDS:
        copied[field] = list(copied.get(field) or [])
    copied["custom_fields"] = list(
        copied.get("custom_fields") or copied.get("annotation_fields") or []
    )
    copied["annotation_fields"] = list(copied["custom_fields"])
    copied["default_field_ortholog"] = dict(copied.get("default_field_ortholog") or {})
    copied["go_resolution_enabled"] = bool(
        copied.get("go_resolution_enabled", False)
    )
    return copied


def _serialize_custom_fields(profile):
    custom = getattr(profile, "custom_fields", ()) or ()
    return [
        field_def.to_dict() if hasattr(field_def, "to_dict") else dict(field_def)
        for field_def in custom
    ]


def _normalize_custom_fields_payload(payload, kegg_code):
    raw = payload.get("custom_fields")
    if raw is None:
        raw = payload.get("annotation_fields") or []
    if not isinstance(raw, list):
        raise InvalidProfileError("custom_fields must be a list")
    default_keys = {item.key for item in field_defs.REQUIRED_DEFAULT_FIELDS}
    parsed = []
    for item in raw:
        if not isinstance(item, dict):
            raise InvalidProfileError("each custom field must be an object")
        field_def = field_defs.AnnotationFieldDef.from_mapping(item)
        if field_def.key in default_keys:
            raise InvalidProfileError(
                f"cannot override required default field {field_def.key!r}"
            )
        if field_def.ortholog_allowed and not kegg_code:
            raise InvalidProfileError(
                f"ortholog_allowed requires kegg_organism_code (field {field_def.key!r})"
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
                f"ortholog_allowed requires kegg_organism_code (default field {key!r})"
            )
    base = {field.key: field.ortholog_allowed for field in field_defs.REQUIRED_DEFAULT_FIELDS}
    base.update(settings)
    return base


def _serialize_default_field_ortholog(profile):
    base = {field.key: field.ortholog_allowed for field in field_defs.REQUIRED_DEFAULT_FIELDS}
    raw = getattr(profile, "default_field_ortholog", ()) or ()
    if isinstance(raw, dict):
        base.update({key: bool(value) for key, value in raw.items()})
    else:
        base.update({key: bool(value) for key, value in raw})
    return base


def _profile_to_document(profile):
    document = asdict(profile)
    for field in PROFILE_ARRAY_FIELDS:
        document[field] = list(document.get(field) or [])
    custom_fields = _serialize_custom_fields(profile)
    document["custom_fields"] = custom_fields
    document["annotation_fields"] = custom_fields
    document["default_field_ortholog"] = _serialize_default_field_ortholog(profile)
    document.pop("annotation_table_path", None)
    document.pop("annotation_id_column", None)
    document.pop("annotation_name_column", None)
    document.pop("annotation_feature_column", None)
    document.pop("annotation_feature_value", None)
    now = _now_iso()
    document["created_at"] = now
    document["updated_at"] = now
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


def _validate_kegg_locus_regex(value):
    """Require a compilable regex with exactly one capturing group."""
    try:
        pattern = re.compile(value)
    except re.error as exc:
        raise InvalidProfileError(f"invalid kegg_locus_regex: {exc}") from exc
    if pattern.groups != 1:
        raise InvalidProfileError(
            "kegg_locus_regex must contain exactly one capturing group "
            "(group 1 becomes the KEGG gene id)"
        )


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
    kegg_locus_regex = _optional_text(payload, "kegg_locus_regex")
    if kegg_locus_regex is not None:
        _validate_kegg_locus_regex(kegg_locus_regex)

    now = _now_iso()
    document: dict[str, Any] = {
        "profile_id": profile_id,
        "canonical_name": canonical_name,
        "species_name": species_name,
        "strain": _optional_text(payload, "strain"),
        "locus_regex": locus_regex,
        "go_resolution_enabled": bool(payload.get("go_resolution_enabled", False)),
        "created_at": now,
        "updated_at": now,
    }
    for field in PROFILE_ARRAY_FIELDS:
        document[field] = _list_field(payload, field)
    document["kegg_organism_code"] = _optional_text(payload, "kegg_organism_code")
    document["kegg_locus_regex"] = kegg_locus_regex
    document["custom_fields"] = _normalize_custom_fields_payload(
        payload,
        document["kegg_organism_code"],
    )
    document["annotation_fields"] = list(document["custom_fields"])
    document["default_field_ortholog"] = _normalize_default_field_ortholog_payload(
        payload,
        document["kegg_organism_code"],
    )
    if not document["target_patterns"]:
        document["target_patterns"] = _default_target_patterns(document)
    for field in PROFILE_REGEX_FIELDS:
        for pattern in document[field]:
            _validate_regex(pattern, field)
    return document


def _safe_profile_filename(profile_id: str) -> str:
    if not profile_id or profile_id in {".", ".."}:
        raise InvalidProfileError("invalid profile_id")
    if "/" in profile_id or "\\" in profile_id or profile_id.startswith("."):
        raise InvalidProfileError("invalid profile_id")
    return f"{profile_id}.json"


class LocalProfileStore:
    """Filesystem-backed organism profile store.

    Profiles live as one JSON file per id under ``directory``. On first use the
    store seeds any missing files from ``seed_catalog_dir`` (defaults to the
    repo ``data/profiles`` catalog via ``organisms.seed_catalog_dir()``), then
    writes a marker so deliberate deletes stick.
    """

    def __init__(self, directory, *, seed_catalog_dir=None, seed_profiles=None):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        # seed_profiles kept for tests that pass OrganismProfile tuples explicitly.
        if seed_profiles is not None:
            self._seed_from_profiles(seed_profiles)
        else:
            catalog = (
                Path(seed_catalog_dir)
                if seed_catalog_dir is not None
                else organisms.seed_catalog_dir()
            )
            self._seed_from_catalog_dir(catalog)

    def health(self):
        return {
            "status": "ok",
            "backend": "local",
            "directory": str(self.directory),
        }

    def _seed_marker_path(self):
        return self.directory / SEED_MARKER_NAME

    def _seed_from_profiles(self, seed_profiles):
        marker = self._seed_marker_path()
        if marker.exists():
            return
        for profile in seed_profiles:
            path = self._profile_path(profile.profile_id)
            if path.exists():
                continue
            self._write_document(_profile_to_document(profile))
        marker.write_text("1\n", encoding="utf-8")

    def _seed_from_catalog_dir(self, catalog_dir: Path):
        marker = self._seed_marker_path()
        if marker.exists():
            return
        catalog_dir = Path(catalog_dir)
        try:
            same = catalog_dir.resolve() == self.directory.resolve()
        except OSError:
            same = False
        if catalog_dir.is_dir() and not same:
            for path in sorted(catalog_dir.glob("*.json")):
                dest = self.directory / path.name
                if dest.exists():
                    continue
                try:
                    shutil.copyfile(path, dest)
                except OSError as exc:
                    raise ProfileStoreUnavailable(
                        f"failed to seed profile {path.name}: {exc}"
                    ) from exc
        marker.write_text("1\n", encoding="utf-8")

    def _profile_path(self, profile_id):
        return self.directory / _safe_profile_filename(profile_id)

    def _read_document(self, path: Path):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ProfileStoreUnavailable(
                f"failed to read profile {path.name}: {exc}"
            ) from exc
        if not isinstance(payload, dict):
            raise ProfileStoreUnavailable(f"invalid profile document: {path.name}")
        return payload

    def _write_document(self, document):
        path = self._profile_path(document["profile_id"])
        try:
            path.write_text(
                json.dumps(document, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        except OSError as exc:
            raise ProfileStoreUnavailable(
                f"failed to write profile {path.name}: {exc}"
            ) from exc

    def list_profiles(self):
        profiles = []
        for path in sorted(self.directory.glob("*.json")):
            document = self._read_document(path)
            profiles.append(_copy_document(document))
        return profiles

    def get_profile(self, profile_id):
        path = self._profile_path(profile_id)
        if not path.is_file():
            return None
        return _copy_document(self._read_document(path))

    def create_profile(self, payload):
        document = _normalize_profile_payload(payload)
        profile_id = document["profile_id"]
        path = self._profile_path(profile_id)
        if path.exists():
            raise DuplicateProfileError(f"profile already exists: {profile_id}")
        self._write_document(document)
        return _copy_document(document)

    def update_profile(self, profile_id, payload):
        path = self._profile_path(profile_id)
        if not path.is_file():
            return None
        existing = self._read_document(path)
        _ensure_profile_id_matches(profile_id, payload)
        document = _normalize_profile_payload({**payload, "profile_id": profile_id})
        document["created_at"] = existing.get("created_at") or document["created_at"]
        document["updated_at"] = _now_iso()
        self._write_document(document)
        return _copy_document(document)

    def delete_profile(self, profile_id):
        path = self._profile_path(profile_id)
        if not path.is_file():
            return False
        try:
            path.unlink()
        except OSError as exc:
            raise ProfileStoreUnavailable(
                f"failed to delete profile {path.name}: {exc}"
            ) from exc
        return True

    # API compatibility aliases (formerly "user" CRUD on the merge store).
    def create_user_profile(self, payload):
        return self.create_profile(payload)

    def update_user_profile(self, profile_id, payload):
        return self.update_profile(profile_id, payload)

    def delete_user_profile(self, profile_id):
        return self.delete_profile(profile_id)


def profile_store_from_env():
    directory = os.getenv("PROFILES_DIR") or DEFAULT_PROFILES_DIR
    return LocalProfileStore(directory)


def user_profile_store_from_env():
    """Deprecated alias for :func:`profile_store_from_env`."""
    return profile_store_from_env()
