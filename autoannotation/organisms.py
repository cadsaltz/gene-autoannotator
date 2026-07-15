import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from . import field_defs
from . import gene_names

# Organism profiles are the boundary between general annotation logic and
# organism-specific assumptions. The catalog lives on disk as one JSON file per
# profile under PROFILES_DIR (default: data/profiles).

class UnknownOrganismError(ValueError):
    """Raised when an organism identifier does not resolve to a configured profile."""


class DuplicateOrganismSynonymError(ValueError):
    """Raised when two profiles claim the same normalized organism synonym."""


class InvalidLocusError(ValueError):
    """Raised when a locus does not match the resolved organism profile."""


@dataclass(frozen=True)
class OrganismProfile:
    profile_id: str
    canonical_name: str
    species_name: str
    strain: str | None
    synonyms: tuple[str, ...]
    species_synonyms: tuple[str, ...]
    strain_synonyms: tuple[str, ...]
    locus_regex: str
    search_terms: tuple[str, ...]
    target_patterns: tuple[str, ...] = ()
    off_target_patterns: tuple[str, ...] = ()
    excluded_species_patterns: tuple[str, ...] = ()
    annotation_table_path: str | None = None
    annotation_id_column: str | None = None
    annotation_name_column: str | None = None
    annotation_feature_column: str | None = None
    annotation_feature_value: str | None = None
    kegg_organism_code: str | None = None
    # Optional regex with one capture group: group 1 is the KEGG SSDB gene id.
    kegg_locus_regex: str | None = None
    custom_fields: tuple = ()
    default_field_ortholog: tuple = ()
    annotation_fields: tuple = ()  # legacy alias; use custom_fields


@dataclass(frozen=True)
class GeneContext:
    profile: OrganismProfile
    locus: str
    gene_name: str
    gene_name_source: str
    gene_name_source_detail: str | None = None
    gene_name_confidence: str | None = None
    gene_name_aliases: list[str] | None = None
    gene_name_candidates: list[str] | None = None
    gene_name_warnings: list[str] | None = None

    def to_metadata(self):
        return {
            'profile_id': self.profile.profile_id,
            'canonical_name': self.profile.canonical_name,
            'species_name': self.profile.species_name,
            'strain': self.profile.strain,
            'gene_name_source': self.gene_name_source,
            'gene_name_source_detail': self.gene_name_source_detail,
            'gene_name_confidence': self.gene_name_confidence,
            'gene_name_aliases': list(self.gene_name_aliases or []),
            'gene_name_candidates': list(self.gene_name_candidates or []),
            'gene_name_warnings': list(self.gene_name_warnings or []),
        }


@dataclass(frozen=True)
class LocusValidationResult:
    valid: bool
    profile_id: str | None
    canonical_name: str | None
    species_name: str | None
    strain: str | None
    supplied_organism: str
    supplied_locus: str
    normalized_locus: str
    matched_organism_synonym: str | None
    matched_locus_schema: bool
    reason: str | None = None

    def to_dict(self):
        return asdict(self)



DEFAULT_PROFILES_DIR = "data/profiles"
_SKIP_PROFILE_NAMES = {".gitkeep", ".seeded"}

_loaded_dir: Path | None = None
_profiles: tuple[OrganismProfile, ...] = ()
_profile_by_synonym: dict = {}
_profiles_by_species_synonym: dict = {}


def profiles_dir() -> Path:
    """Active catalog used by resolve_profile (honors PROFILES_DIR)."""
    return Path(os.getenv("PROFILES_DIR") or DEFAULT_PROFILES_DIR)


def seed_catalog_dir() -> Path:
    """Canonical on-disk catalog used to seed empty LocalProfileStore dirs.

    Defaults to ``data/profiles`` (or PROFILES_SEED_DIR). Independent of
    PROFILES_DIR so tests can point PROFILES_DIR at a temp folder and still
    seed from the repo catalog.
    """
    return Path(os.getenv("PROFILES_SEED_DIR") or DEFAULT_PROFILES_DIR)


def _load_profiles_from_directory(directory: Path) -> tuple[OrganismProfile, ...]:
    if not directory.is_dir():
        return ()
    profiles: list[OrganismProfile] = []
    for path in sorted(directory.glob("*.json")):
        if path.name in _SKIP_PROFILE_NAMES:
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"failed to read organism profile {path}: {exc}") from exc
        if not isinstance(payload, dict) or not payload.get("profile_id"):
            raise RuntimeError(f"invalid organism profile document: {path}")
        profiles.append(profile_from_mapping(payload))
    return tuple(profiles)


def reload_profiles(*, directory: Path | None = None) -> tuple[OrganismProfile, ...]:
    """Reload the in-process catalog from disk. Used by tests and after writes."""
    global _loaded_dir, _profiles, _profile_by_synonym, _profiles_by_species_synonym
    directory = (directory or profiles_dir()).resolve()
    profiles = _load_profiles_from_directory(directory)
    _profiles = profiles
    _profile_by_synonym = _build_synonym_index(profiles)
    _profiles_by_species_synonym = _build_species_index(profiles)
    _loaded_dir = directory
    return profiles


def _ensure_profiles_loaded() -> None:
    directory = profiles_dir().resolve()
    if _loaded_dir != directory:
        reload_profiles(directory=directory)


def all_profiles() -> tuple[OrganismProfile, ...]:
    _ensure_profiles_loaded()
    return _profiles


def normalize_identifier(identifier):
    return re.sub(r"[^a-z0-9]+", "", identifier.casefold())


def _build_synonym_index(profiles):
    # Profile synonyms must be unique because API/CLI callers may use any
    # synonym as the primary profile identifier.
    index = {}
    for profile in profiles:
        identifiers = (profile.profile_id, profile.canonical_name, *profile.synonyms)
        for synonym in identifiers:
            normalized = normalize_identifier(synonym)
            existing = index.get(normalized)
            if existing is not None and existing.profile_id != profile.profile_id:
                raise DuplicateOrganismSynonymError(
                    f'Organism synonym "{synonym}" is shared by '
                    f"{existing.profile_id} and {profile.profile_id}"
                )
            index[normalized] = profile
    return index


def _build_species_index(profiles):
    # Species names can map to multiple strains. Later validation narrows those
    # candidates with strain input and/or locus regex.
    index = {}
    for profile in profiles:
        identifiers = (profile.species_name, *profile.species_synonyms)
        for synonym in identifiers:
            normalized = normalize_identifier(synonym)
            index.setdefault(normalized, [])
            if profile not in index[normalized]:
                index[normalized].append(profile)
    return index


def resolve_profile(identifier):
    _ensure_profiles_loaded()
    normalized = normalize_identifier(identifier)
    try:
        return _profile_by_synonym[normalized]
    except KeyError as exc:
        raise UnknownOrganismError(f"Unknown organism profile: {identifier}") from exc


def resolve_species_profiles(identifier):
    _ensure_profiles_loaded()
    normalized = normalize_identifier(identifier)
    try:
        return tuple(_profiles_by_species_synonym[normalized])
    except KeyError as exc:
        raise UnknownOrganismError(f"Unknown organism species: {identifier}") from exc


def _matches_strain(profile, strain_identifier):
    if profile.strain is None:
        return strain_identifier is None
    normalized = normalize_identifier(strain_identifier)
    identifiers = (profile.strain, *profile.strain_synonyms)
    return normalized in {normalize_identifier(identifier) for identifier in identifiers}


def validate_locus(profile, locus):
    return re.fullmatch(profile.locus_regex, locus) is not None


def _optional_stripped(value):
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def profile_from_mapping(payload):
    raw_custom = payload.get('custom_fields')
    if raw_custom is None:
        raw_custom = payload.get('annotation_fields')
    custom_fields = field_defs.custom_fields_from_mappings(raw_custom or ())
    kegg_code = payload.get('kegg_organism_code')
    if kegg_code is not None:
        kegg_code = str(kegg_code).strip() or None
    default_field_ortholog = field_defs.default_field_ortholog_from_mapping(payload)
    return OrganismProfile(
        profile_id=payload["profile_id"],
        canonical_name=payload["canonical_name"],
        species_name=payload["species_name"],
        strain=payload.get("strain"),
        synonyms=tuple(payload.get("synonyms") or ()),
        species_synonyms=tuple(payload.get("species_synonyms") or ()),
        strain_synonyms=tuple(payload.get("strain_synonyms") or ()),
        locus_regex=payload.get("locus_regex") or "",
        search_terms=tuple(payload.get("search_terms") or ()),
        target_patterns=tuple(payload.get("target_patterns") or ()),
        off_target_patterns=tuple(payload.get("off_target_patterns") or ()),
        excluded_species_patterns=tuple(payload.get("excluded_species_patterns") or ()),
        annotation_table_path=payload.get("annotation_table_path"),
        annotation_id_column=payload.get("annotation_id_column"),
        annotation_name_column=payload.get("annotation_name_column"),
        annotation_feature_column=payload.get("annotation_feature_column"),
        annotation_feature_value=payload.get("annotation_feature_value"),
        kegg_organism_code=kegg_code,
        kegg_locus_regex=_optional_stripped(payload.get("kegg_locus_regex")),
        custom_fields=custom_fields,
        default_field_ortholog=tuple(default_field_ortholog.items()),
        annotation_fields=custom_fields,
    )


def _result_for_profile(profile, organism_identifier, locus, *, valid, reason=None):
    return LocusValidationResult(
        valid=valid,
        profile_id=profile.profile_id,
        canonical_name=profile.canonical_name,
        species_name=profile.species_name,
        strain=profile.strain,
        supplied_organism=organism_identifier,
        supplied_locus=locus,
        normalized_locus=locus,
        matched_organism_synonym=organism_identifier,
        matched_locus_schema=valid,
        reason=reason,
    )


def _invalid_result(organism_identifier, locus, reason):
    return LocusValidationResult(
        valid=False,
        profile_id=None,
        canonical_name=None,
        species_name=None,
        strain=None,
        supplied_organism=organism_identifier,
        supplied_locus=locus,
        normalized_locus=locus,
        matched_organism_synonym=None,
        matched_locus_schema=False,
        reason=reason,
    )


def validate_locus_request(
    *,
    locus,
    profile_identifier=None,
    organism_identifier=None,
    strain_identifier=None,
):
    if profile_identifier is not None:
        try:
            profile = resolve_profile(profile_identifier)
        except UnknownOrganismError:
            return _invalid_result(profile_identifier, locus, "unknown_profile")
        matched_locus_schema = validate_locus(profile, locus)
        return _result_for_profile(
            profile,
            profile_identifier,
            locus,
            valid=matched_locus_schema,
            reason=None if matched_locus_schema else "locus_schema_mismatch",
        )

    if organism_identifier is None:
        raise ValueError("organism_identifier or profile_identifier is required")

    try:
        candidate_profiles = resolve_species_profiles(organism_identifier)
    except UnknownOrganismError:
        return _invalid_result(organism_identifier, locus, "unknown_organism")

    if strain_identifier is not None:
        candidate_profiles = tuple(
            profile for profile in candidate_profiles
            if _matches_strain(profile, strain_identifier)
        )
        if not candidate_profiles:
            return _invalid_result(organism_identifier, locus, "unknown_strain")

    matching_profiles = [
        profile for profile in candidate_profiles
        if validate_locus(profile, locus)
    ]
    if len(matching_profiles) == 1:
        return _result_for_profile(matching_profiles[0], organism_identifier, locus, valid=True)
    if len(matching_profiles) > 1:
        return _invalid_result(organism_identifier, locus, "ambiguous_profile")
    return _invalid_result(organism_identifier, locus, "locus_schema_mismatch")


def validate_organism_locus(organism_identifier, locus):
    try:
        resolve_profile(organism_identifier)
    except UnknownOrganismError:
        return validate_locus_request(
            organism_identifier=organism_identifier,
            locus=locus,
        )
    return validate_locus_request(
        profile_identifier=organism_identifier,
        locus=locus,
    )


def _profile_from_validation_result(result):
    if not result.valid:
        raise InvalidLocusError(
            f"Invalid locus {result.supplied_locus!r} for organism/profile "
            f"{result.supplied_organism!r}: {result.reason}"
        )
    return resolve_profile(result.profile_id)


def resolve_gene_context(
    *,
    locus,
    profile_identifier=None,
    organism_identifier=None,
    strain_identifier=None,
    name=None,
    gene_name_cache_dir=gene_names.DEFAULT_GENE_NAME_CACHE_DIR,
    allow_online_name_lookup=False,
    refresh_gene_name_cache=False,
    gene_name_sources=None,
    cache_supplied_name=False,
):
    # Context resolution validates the locus before any network or model work,
    # then chooses the best available gene name. The returned GeneContext is the
    # stable handoff object for retrieval, prompting, and metadata.
    result = validate_locus_request(
        locus=locus,
        profile_identifier=profile_identifier,
        organism_identifier=organism_identifier,
        strain_identifier=strain_identifier,
    )
    profile = _profile_from_validation_result(result)

    if name:
        if cache_supplied_name:
            gene_names.cache_supplied_gene_name(
                profile,
                locus,
                name,
                cache_dir=gene_name_cache_dir,
            )
        return GeneContext(
            profile=profile,
            locus=locus,
            gene_name=name,
            gene_name_source='supplied',
            gene_name_source_detail='supplied argument',
            gene_name_confidence='curator_supplied',
            gene_name_aliases=[],
            gene_name_candidates=[],
            gene_name_warnings=[],
        )

    lookup_result = gene_names.resolve_gene_name(
        profile,
        locus,
        cache_dir=gene_name_cache_dir,
        allow_online_lookup=allow_online_name_lookup,
        refresh_cache=refresh_gene_name_cache,
        sources=gene_name_sources,
    )
    return GeneContext(
        profile=profile,
        locus=locus,
        gene_name=lookup_result.gene_name,
        gene_name_source=lookup_result.source,
        gene_name_source_detail=lookup_result.source_detail,
        gene_name_confidence=lookup_result.confidence,
        gene_name_aliases=list(lookup_result.aliases),
        gene_name_candidates=list(lookup_result.candidates),
        gene_name_warnings=list(lookup_result.warnings),
    )
