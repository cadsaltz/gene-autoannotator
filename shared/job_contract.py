from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from autoannotation import gene_names


def _normalize_optional_string(value):
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


class OrthologOverride(BaseModel):
    """Manual gene override (profile + locus) or profile-only search constraint."""

    profile_id: str = Field(min_length=1)
    locus: str | None = None
    name: str | None = None

    @field_validator("profile_id", "locus", "name", mode="before")
    @classmethod
    def normalize_strings(cls, value):
        return _normalize_optional_string(value)

    @model_validator(mode="after")
    def validate_override_shape(self):
        if self.name and not self.locus:
            raise ValueError("ortholog override name requires locus")
        return self


class AnnotationJobRequest(BaseModel):
    # cache/output fields are server filesystem paths passed through to the
    # existing annotator. Add validation here before exposing this API beyond a
    # trusted/local deployment.
    profile: str | None = None
    organism: str | None = None
    strain: str | None = None
    locus: str | None = None
    name: str | None = None
    cache_dir: str = "./.cache"
    output_dir: str = "gen_json"
    gene_name_cache: str = gene_names.DEFAULT_GENE_NAME_CACHE_DIR
    allow_online_name_lookup: bool = True
    refresh_gene_name_cache: bool = False
    cache_supplied_name: bool = False
    # Job-time snapshots. Public/list APIs strip these; workers must receive them
    # (subprocess serialization uses model_dump, so do NOT mark exclude=True).
    profile_config: dict[str, Any] | None = None
    ortholog_profile_catalog: list[dict[str, Any]] = Field(default_factory=list)
    locus_regex: str | None = None
    search_terms: list[str] = Field(default_factory=list)
    target_patterns: list[str] = Field(default_factory=list)
    off_target_patterns: list[str] = Field(default_factory=list)
    excluded_species_patterns: list[str] = Field(default_factory=list)
    kegg_organism_code: str | None = None
    annotation_fields: list[dict[str, object]] = Field(default_factory=list)
    allow_ortholog_fallback: bool = False
    ortholog_override: OrthologOverride | None = None

    @field_validator(
        "profile",
        "organism",
        "strain",
        "locus",
        "name",
        "locus_regex",
        mode="before",
    )
    @classmethod
    def normalize_optional_strings(cls, value):
        return _normalize_optional_string(value)

    @model_validator(mode="after")
    def validate_target_shape(self):
        if self.profile and self.organism:
            raise ValueError("use either profile or organism, not both")
        if not self.profile and not self.organism:
            raise ValueError("profile or organism is required")
        if not self.locus and not self.name:
            raise ValueError("name or locus is required")
        if self.ortholog_override and not self.allow_ortholog_fallback:
            raise ValueError("ortholog_override requires allow_ortholog_fallback=true")
        return self
