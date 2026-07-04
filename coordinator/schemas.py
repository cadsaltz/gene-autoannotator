from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from autoannotation import field_defs
from autoannotation import gene_names


def _normalize_optional_string(value):
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


class OrthologOverride(BaseModel):
    profile_id: str = Field(min_length=1)
    locus: str = Field(min_length=1)
    name: str | None = None

    @field_validator("profile_id", "locus", "name", mode="before")
    @classmethod
    def normalize_strings(cls, value):
        return _normalize_optional_string(value)


class AnnotationFieldPayload(BaseModel):
    key: str = Field(min_length=1)
    label: str = Field(min_length=1)
    description: str = Field(min_length=1)
    type: Literal['string', 'boolean', 'array:string'] = 'string'
    required: bool = False
    inference_strategy: Literal['paper_llm', 'go_terms', 'essentiality_db'] = 'paper_llm'
    ortholog_allowed: bool = False


class ProfilePayload(BaseModel):
    profile_id: str = Field(min_length=1)
    canonical_name: str = Field(min_length=1)
    species_name: str = Field(min_length=1)
    strain: str | None = None
    synonyms: list[str] = Field(default_factory=list)
    species_synonyms: list[str] = Field(default_factory=list)
    strain_synonyms: list[str] = Field(default_factory=list)
    locus_regex: str | None = None
    search_terms: list[str] = Field(default_factory=list)
    target_patterns: list[str] = Field(default_factory=list)
    off_target_patterns: list[str] = Field(default_factory=list)
    excluded_species_patterns: list[str] = Field(default_factory=list)
    kegg_organism_code: str | None = None
    custom_fields: list[AnnotationFieldPayload] = Field(default_factory=list)
    annotation_fields: list[AnnotationFieldPayload] = Field(default_factory=list)
    default_field_ortholog: dict[str, bool] = Field(default_factory=dict)

    @field_validator('kegg_organism_code', mode='before')
    @classmethod
    def normalize_kegg_code(cls, value):
        return _normalize_optional_string(value)

    @model_validator(mode='after')
    def normalize_custom_fields(self):
        custom = self.custom_fields or self.annotation_fields or []
        kegg_code = self.kegg_organism_code
        normalized = []
        for item in custom:
            field_def = field_defs.AnnotationFieldDef.from_mapping(item.model_dump())
            field_defs.validate_custom_field(field_def)
            if field_def.ortholog_allowed and not kegg_code:
                raise ValueError(
                    f'ortholog_allowed requires kegg_organism_code (field {field_def.key!r})'
                )
            normalized.append(field_def)
        field_defs.validate_custom_fields(tuple(normalized))
        object.__setattr__(self, 'custom_fields', [
            AnnotationFieldPayload(**field_def.to_dict()) for field_def in normalized
        ])
        object.__setattr__(self, 'annotation_fields', self.custom_fields)
        object.__setattr__(
            self,
            'default_field_ortholog',
            field_defs.default_field_ortholog_from_mapping({
                'default_field_ortholog': self.default_field_ortholog,
            }),
        )
        if self.default_field_ortholog:
            kegg_code = self.kegg_organism_code
            for key, enabled in self.default_field_ortholog.items():
                if enabled and not kegg_code:
                    raise ValueError(
                        f'ortholog_allowed requires kegg_organism_code (default field {key!r})'
                    )
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
    profile_config: dict[str, Any] | None = Field(default=None, exclude=True)
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


class ValidationRequest(BaseModel):
    profile: str | None = None
    organism: str | None = None
    strain: str | None = None
    locus: str | None = None
    name: str | None = None
    locus_regex: str | None = None
    search_terms: list[str] = Field(default_factory=list)
    target_patterns: list[str] = Field(default_factory=list)
    off_target_patterns: list[str] = Field(default_factory=list)
    excluded_species_patterns: list[str] = Field(default_factory=list)
    kegg_organism_code: str | None = None
    annotation_fields: list[dict[str, object]] = Field(default_factory=list)

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
        return self


class BatchEntryInput(BaseModel):
    input: str | None = None
    locus: str | None = None
    name: str | None = None
    selected_locus: str | None = None

    @field_validator("input", "locus", "name", "selected_locus", mode="before")
    @classmethod
    def normalize_batch_strings(cls, value):
        return _normalize_optional_string(value)

    @model_validator(mode="after")
    def validate_shape(self):
        if not self.input and not self.locus and not self.name:
            raise ValueError("input, locus, or name is required")
        return self


class BatchJobOptions(BaseModel):
    profile: str | None = None
    organism: str | None = None
    strain: str | None = None
    cache_dir: str = "./.cache"
    output_dir: str = "gen_json"
    gene_name_cache: str = gene_names.DEFAULT_GENE_NAME_CACHE_DIR
    allow_online_name_lookup: bool = True
    refresh_gene_name_cache: bool = False
    cache_supplied_name: bool = False
    locus_regex: str | None = None
    search_terms: list[str] = Field(default_factory=list)
    target_patterns: list[str] = Field(default_factory=list)
    off_target_patterns: list[str] = Field(default_factory=list)
    excluded_species_patterns: list[str] = Field(default_factory=list)
    allow_ortholog_fallback: bool = False

    @field_validator(
        "profile",
        "organism",
        "strain",
        "locus_regex",
        mode="before",
    )
    @classmethod
    def normalize_optional_strings(cls, value):
        return _normalize_optional_string(value)

    @model_validator(mode="after")
    def validate_profile_shape(self):
        if self.profile and self.organism:
            raise ValueError("use either profile or organism, not both")
        if not self.profile and not self.organism:
            raise ValueError("profile or organism is required")
        return self


class BatchValidateRequest(BatchJobOptions):
    entries: list[BatchEntryInput] = Field(min_length=1)
    raw_text: str | None = None


class BatchCreateRequest(BatchValidateRequest):
    pass


class BatchPreviewSummary(BaseModel):
    total: int
    ready: int
    ambiguous: int
    invalid: int
    duplicate_skipped: int


class ProfileResponse(BaseModel):
    profile_id: str
    canonical_name: str
    species_name: str
    strain: str | None
    synonyms: list[str]
    species_synonyms: list[str]
    strain_synonyms: list[str]
    locus_regex: str | None


class RegexFromExamplesRequest(BaseModel):
    examples: list[str] = Field(default_factory=list)


class RegexFromDescriptionRequest(BaseModel):
    description: str = Field(min_length=1)

    @field_validator("description", mode="before")
    @classmethod
    def normalize_description(cls, value):
        if isinstance(value, str):
            return value.strip()
        return value


class ProfileDetailResponse(ProfileResponse):
    source: str = "builtin"
    trusted: bool = True
    read_only: bool = False
    search_terms: list[str] = Field(default_factory=list)
    target_patterns: list[str] = Field(default_factory=list)
    off_target_patterns: list[str] = Field(default_factory=list)
    excluded_species_patterns: list[str] = Field(default_factory=list)
    kegg_organism_code: str | None = None
    custom_fields: list[dict[str, Any]] = Field(default_factory=list)
    annotation_fields: list[dict[str, Any]] = Field(default_factory=list)
    default_field_ortholog: dict[str, bool] = Field(default_factory=dict)
    created_at: str | None = None
    updated_at: str | None = None


class ProfilesResponse(BaseModel):
    profiles: list[ProfileDetailResponse]


class TargetWarning(BaseModel):
    code: str
    message: str


class TargetPreflightResponse(BaseModel):
    valid: bool = True
    profile_id: str | None = None
    profile_source: str = "ad_hoc"
    canonical_name: str | None = None
    species_name: str | None = None
    strain: str | None = None
    submitted_locus: str | None = None
    submitted_name: str | None = None
    resolved_locus: str | None = None
    resolved_name: str | None = None
    primary_identifier: str
    warnings: list[TargetWarning] = Field(default_factory=list)


class BatchEntryPreview(BaseModel):
    line: int
    input: str
    submitted_locus: str | None = None
    submitted_name: str | None = None
    resolved_locus: str | None = None
    resolved_name: str | None = None
    primary_identifier: str | None = None
    match_method: str | None = None
    status: Literal["ready", "ambiguous", "invalid", "duplicate_skipped"]
    warnings: list[TargetWarning] = Field(default_factory=list)
    candidates: list[str] = Field(default_factory=list)


class BatchValidateResponse(BaseModel):
    summary: BatchPreviewSummary
    entries: list[BatchEntryPreview]


class BatchCreateResponse(BaseModel):
    batch_id: str
    job_ids: list[str]
    skipped: list[BatchEntryPreview]
    summary: BatchPreviewSummary


class JobCreateResponse(BaseModel):
    job_id: str
    status: str


class JobRecordResponse(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    id: str
    status: str
    current_step: str = "queued"
    request: dict[str, Any]
    result: dict[str, Any] | None = None
    error: str | None = None
    annotation_persisted: bool = False
    annotation_error: str | None = None
    output_path: str | None = None
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    result_available: bool = False
    queue_position: int | None = None


class QueueSummaryResponse(BaseModel):
    queued: int
    running: int
    completed: int
    failed: int


class BatchDetailResponse(BaseModel):
    id: str
    status: str
    profile: str | None = None
    organism: str | None = None
    strain: str | None = None
    created_at: str
    summary: BatchPreviewSummary
    queue: QueueSummaryResponse


class JobsListResponse(BaseModel):
    jobs: list[JobRecordResponse]
    queue: QueueSummaryResponse


class AnnotationSearchResult(BaseModel):
    id: str
    profile_id: str
    canonical_name: str
    species_name: str | None = None
    strain: str | None = None
    normalized_locus: str | None = None
    gene_name: str | None = None
    generated_at: str | None = None
    version_count: int = 0


class AnnotationSearchResponse(BaseModel):
    query: str
    matches: list[AnnotationSearchResult]


class AnnotationDetailResponse(AnnotationSearchResult):
    result: dict[str, Any]
    job_id: str | None = None
    output_path: str | None = None


class AnnotationVersionsResponse(BaseModel):
    annotation_id: str
    versions: list[dict[str, Any]]
