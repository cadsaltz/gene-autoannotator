from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field

from . import gene_names, organisms

AD_HOC_PROFILE = 'ad_hoc_profile'
MISSING_LOCUS = 'missing_locus'
MISSING_GENE_NAME = 'missing_gene_name'
LOCUS_NOT_VALIDATED = 'locus_not_validated'
LOCUS_SCHEMA_MISMATCH = 'locus_schema_mismatch'
NAME_TO_LOCUS_UNAVAILABLE = 'name_to_locus_unavailable'

TARGET_WARNING_MESSAGES = {
    AD_HOC_PROFILE: 'Using an ad hoc organism profile.',
    MISSING_LOCUS: 'No locus identifier was supplied.',
    MISSING_GENE_NAME: 'No gene name was supplied.',
    LOCUS_NOT_VALIDATED: 'Locus was not validated because the profile has no locus schema.',
    LOCUS_SCHEMA_MISMATCH: 'Locus does not match the profile locus schema.',
    NAME_TO_LOCUS_UNAVAILABLE: 'Gene name could not be resolved to a locus identifier.',
}


@dataclass(frozen=True)
class AnnotationTarget:
    profile: organisms.OrganismProfile
    submitted_locus: str | None
    submitted_name: str | None
    resolved_locus: str | None
    resolved_name: str | None
    primary_identifier: str
    profile_source: str
    warnings: list[str]
    gene_name_source: str | None = None
    gene_name_source_detail: str | None = None
    gene_name_confidence: str | None = None
    gene_name_aliases: list[str] = field(default_factory=list)
    gene_name_candidates: list[str] = field(default_factory=list)
    gene_name_warnings: list[str] = field(default_factory=list)
    locus_lookup_source: str | None = None
    locus_lookup_source_detail: str | None = None
    locus_lookup_confidence: str | None = None
    locus_lookup_candidates: list[str] = field(default_factory=list)
    locus_lookup_warnings: list[str] = field(default_factory=list)

    def to_preflight_dict(self):
        return {
            'valid': LOCUS_SCHEMA_MISMATCH not in self.warnings,
            'profile_id': self.profile.profile_id,
            'profile_source': self.profile_source,
            'canonical_name': self.profile.canonical_name,
            'species_name': self.profile.species_name,
            'strain': self.profile.strain,
            'submitted_locus': self.submitted_locus,
            'submitted_name': self.submitted_name,
            'resolved_locus': self.resolved_locus,
            'resolved_name': self.resolved_name,
            'primary_identifier': self.primary_identifier,
            'warnings': [
                {
                    'code': warning,
                    'message': TARGET_WARNING_MESSAGES.get(warning, warning),
                }
                for warning in self.warnings
            ],
        }


def _clean_identifier(value):
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _unique(values):
    seen = set()
    unique_values = []
    for value in values:
        if value is None:
            continue
        if value in seen:
            continue
        seen.add(value)
        unique_values.append(value)
    return tuple(unique_values)


def _slug(value):
    slug = re.sub(r'[^a-z0-9]+', '-', value.casefold()).strip('-')
    return slug or 'organism'


def _stable_hash_component(value):
    if value is None:
        return ''
    return re.sub(r'\s+', ' ', value.strip()).casefold()


def build_ad_hoc_profile(
    organism_identifier,
    strain_identifier=None,
    *,
    locus_regex=None,
    search_terms=None,
    target_patterns=None,
    off_target_patterns=None,
    excluded_species_patterns=None,
):
    organism_identifier = _clean_identifier(organism_identifier)
    strain_identifier = _clean_identifier(strain_identifier)
    if organism_identifier is None:
        raise ValueError('organism_identifier is required')

    canonical_name = ' '.join(
        part for part in (organism_identifier, strain_identifier)
        if part
    )
    hash_input = (
        f'{_stable_hash_component(organism_identifier)}\0'
        f'{_stable_hash_component(strain_identifier)}'
    )
    digest = hashlib.sha1(hash_input.encode('utf8')).hexdigest()[:10]
    profile_id = f'ad-hoc-{_slug(canonical_name)}-{digest}'

    resolved_search_terms = list(search_terms or [])
    resolved_search_terms.extend([organism_identifier, strain_identifier])

    return organisms.OrganismProfile(
        profile_id=profile_id,
        canonical_name=canonical_name,
        species_name=organism_identifier,
        strain=strain_identifier,
        synonyms=_unique([profile_id, canonical_name, organism_identifier]),
        species_synonyms=_unique([organism_identifier]),
        strain_synonyms=_unique([strain_identifier]),
        locus_regex=locus_regex or '',
        search_terms=_unique(resolved_search_terms),
        target_patterns=tuple(target_patterns or (re.escape(organism_identifier),)),
        off_target_patterns=tuple(off_target_patterns or ()),
        excluded_species_patterns=tuple(excluded_species_patterns or ()),
    )


def _profile_from_lookup_result(profile_payload):
    if isinstance(profile_payload, organisms.OrganismProfile):
        return profile_payload, 'local'
    if isinstance(profile_payload, Mapping):
        return organisms.profile_from_mapping(profile_payload), 'local'
    raise TypeError('profile lookup must return an OrganismProfile or mapping')


def _resolve_profile(profile_identifier, profile_lookup):
    if profile_lookup is None:
        return organisms.resolve_profile(profile_identifier), 'local'
    profile_payload = profile_lookup(profile_identifier)
    if profile_payload is None:
        raise organisms.UnknownOrganismError(f'Unknown organism profile: {profile_identifier}')
    return _profile_from_lookup_result(profile_payload)


def _add_warning(warnings, warning):
    if warning not in warnings:
        warnings.append(warning)


def _add_locus_validation_warning(profile, locus, warnings):
    if profile.locus_regex:
        if not organisms.validate_locus(profile, locus):
            _add_warning(warnings, LOCUS_SCHEMA_MISMATCH)
    else:
        _add_warning(warnings, LOCUS_NOT_VALIDATED)


def resolve_annotation_target(
    *,
    profile_identifier,
    organism_identifier,
    strain_identifier,
    locus,
    name,
    profile_lookup: Callable[[str], object] | None = None,
    allow_online_name_lookup=False,
    gene_name_cache_dir=gene_names.DEFAULT_GENE_NAME_CACHE_DIR,
    gene_locus_sources: Sequence[object] | None = None,
    locus_regex=None,
    search_terms=None,
    target_patterns=None,
    off_target_patterns=None,
    excluded_species_patterns=None,
):
    submitted_locus = _clean_identifier(locus)
    submitted_name = _clean_identifier(name)
    if submitted_locus is None and submitted_name is None:
        raise ValueError('name or locus is required')

    warnings = []
    profile_identifier = _clean_identifier(profile_identifier)
    if profile_identifier is not None:
        profile, profile_source = _resolve_profile(profile_identifier, profile_lookup)
    else:
        profile = build_ad_hoc_profile(
            organism_identifier,
            strain_identifier,
            locus_regex=locus_regex,
            search_terms=search_terms,
            target_patterns=target_patterns,
            off_target_patterns=off_target_patterns,
            excluded_species_patterns=excluded_species_patterns,
        )
        profile_source = 'ad_hoc'
        _add_warning(warnings, AD_HOC_PROFILE)

    resolved_locus = None
    resolved_name = submitted_name
    gene_name_result = None
    locus_lookup_result = None

    if submitted_locus is not None:
        resolved_locus = submitted_locus
        _add_locus_validation_warning(profile, resolved_locus, warnings)
    else:
        _add_warning(warnings, MISSING_LOCUS)
        if submitted_name is not None:
            locus_lookup_result = gene_names.resolve_locus_from_gene_name(
                profile,
                submitted_name,
                allow_online_lookup=allow_online_name_lookup,
                sources=gene_locus_sources,
            )
            if locus_lookup_result and locus_lookup_result.locus:
                resolved_locus = locus_lookup_result.locus
                _add_locus_validation_warning(profile, resolved_locus, warnings)
            else:
                _add_warning(warnings, NAME_TO_LOCUS_UNAVAILABLE)

    if submitted_name is None:
        _add_warning(warnings, MISSING_GENE_NAME)
        if resolved_locus is not None:
            gene_name_result = gene_names.resolve_gene_name(
                profile,
                resolved_locus,
                cache_dir=gene_name_cache_dir,
                allow_online_lookup=allow_online_name_lookup,
            )
            resolved_name = gene_name_result.gene_name

    primary_identifier = resolved_locus or resolved_name
    if primary_identifier is None:
        raise ValueError('name or locus is required')

    return AnnotationTarget(
        profile=profile,
        submitted_locus=submitted_locus,
        submitted_name=submitted_name,
        resolved_locus=resolved_locus,
        resolved_name=resolved_name,
        primary_identifier=primary_identifier,
        profile_source=profile_source,
        warnings=warnings,
        gene_name_source=gene_name_result.source if gene_name_result else None,
        gene_name_source_detail=gene_name_result.source_detail if gene_name_result else None,
        gene_name_confidence=gene_name_result.confidence if gene_name_result else None,
        gene_name_aliases=list(gene_name_result.aliases) if gene_name_result else [],
        gene_name_candidates=list(gene_name_result.candidates) if gene_name_result else [],
        gene_name_warnings=list(gene_name_result.warnings) if gene_name_result else [],
        locus_lookup_source=locus_lookup_result.source if locus_lookup_result else None,
        locus_lookup_source_detail=(
            locus_lookup_result.source_detail if locus_lookup_result else None
        ),
        locus_lookup_confidence=locus_lookup_result.confidence if locus_lookup_result else None,
        locus_lookup_candidates=(
            list(locus_lookup_result.candidates) if locus_lookup_result else []
        ),
        locus_lookup_warnings=list(locus_lookup_result.warnings) if locus_lookup_result else [],
    )
