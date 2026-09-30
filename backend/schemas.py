from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    StrictBool,
    StrictInt,
    field_validator,
    model_validator,
)

from autoannotation import field_defs
from autoannotation import gene_names
from shared.job_contract import (
    AnnotationJobRequest,
    OrthologOverride,
    _normalize_optional_string,
)

from .access import ROLES, STATUSES

IDENTIFIER_MAX_LENGTH = 128
ORGANISM_MAX_LENGTH = 200
BATCH_RAW_TEXT_MAX_LENGTH = 200_000
USERNAME_MAX_LENGTH = 64

Identifier = Annotated[str | None, Field(max_length=IDENTIFIER_MAX_LENGTH)]
OrganismText = Annotated[str | None, Field(max_length=ORGANISM_MAX_LENGTH)]
# Regex/pattern fields compiled by the API process; only admins may set them.
ADMIN_ONLY_TARGET_FIELDS = (
    "locus_regex",
    "search_terms",
    "target_patterns",
    "off_target_patterns",
    "excluded_species_patterns",
)


def supplied_admin_only_fields(request) -> list[str]:
    return [field for field in ADMIN_ONLY_TARGET_FIELDS if getattr(request, field, None)]


class BoundedOrthologOverride(OrthologOverride):
    profile_id: str = Field(min_length=1, max_length=IDENTIFIER_MAX_LENGTH)
    locus: Identifier = None
    name: Identifier = None


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
    kegg_locus_regex: str | None = None
    go_resolution_enabled: bool = False
    custom_fields: list[AnnotationFieldPayload] = Field(default_factory=list)
    annotation_fields: list[AnnotationFieldPayload] = Field(default_factory=list)
    default_field_ortholog: dict[str, bool] = Field(default_factory=dict)

    @field_validator('kegg_organism_code', 'kegg_locus_regex', mode='before')
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


class ValidationRequest(BaseModel):
    profile: Identifier = None
    organism: OrganismText = None
    strain: OrganismText = None
    locus: Identifier = None
    name: Identifier = None
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
    input: Identifier = None
    locus: Identifier = None
    name: Identifier = None
    selected_locus: Identifier = None

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
    profile: Identifier = None
    organism: OrganismText = None
    strain: OrganismText = None
    # Ignored on public API; batch jobs use server defaults for path fields.
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
    # Batch jobs may constrain ortholog search to a profile, but must not pin a
    # single ortholog gene for every target in the batch.
    ortholog_override: BoundedOrthologOverride | None = None

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
        if self.ortholog_override and not self.allow_ortholog_fallback:
            raise ValueError("ortholog_override requires allow_ortholog_fallback=true")
        if self.ortholog_override and (
            self.ortholog_override.locus or self.ortholog_override.name
        ):
            raise ValueError(
                "batch ortholog_override may specify profile_id only; "
                "locus and name are not allowed"
            )
        return self


class BatchValidateRequest(BatchJobOptions):
    entries: list[BatchEntryInput] = Field(min_length=1)
    raw_text: str | None = Field(default=None, max_length=BATCH_RAW_TEXT_MAX_LENGTH)


class BatchCreateRequest(BatchValidateRequest):
    pass


class JobSubmitRequest(AnnotationJobRequest):
    profile: Identifier = None
    organism: OrganismText = None
    strain: OrganismText = None
    locus: Identifier = None
    name: Identifier = None
    ortholog_override: BoundedOrthologOverride | None = None


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
    search_terms: list[str] = Field(default_factory=list)
    target_patterns: list[str] = Field(default_factory=list)
    off_target_patterns: list[str] = Field(default_factory=list)
    excluded_species_patterns: list[str] = Field(default_factory=list)
    kegg_organism_code: str | None = None
    kegg_locus_regex: str | None = None
    go_resolution_enabled: bool = False
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
    progress_phase: str | None = None
    sections_done: int | None = None
    sections_total: int | None = None
    pass_name: str | None = None
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
    submitted_by_user_id: str | None = None
    submitted_by_email: str | None = None


class QueueSummaryResponse(BaseModel):
    queued: int
    running: int
    completed: int
    failed: int
    cancelled: int = 0


class QueueStatusResponse(BaseModel):
    queued: int
    accepting: bool
    paused: bool
    your_active: int
    your_active_limit: int | None
    your_today: int
    your_daily_limit: int | None
    batch_limit: int


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


class AuthSignupRequest(BaseModel):
    email: EmailStr
    username: str | None = Field(default=None, max_length=USERNAME_MAX_LENGTH)
    accept_terms: StrictBool

    @field_validator('accept_terms')
    @classmethod
    def validate_accept_terms(cls, value):
        if value is not True:
            raise ValueError(
                'You must agree to the Terms of Service and Acceptable Use Policy'
            )
        return value


class AuthLoginRequest(BaseModel):
    email: EmailStr


class AuthVerifyRequest(BaseModel):
    email: EmailStr
    code: str


class AuthOkResponse(BaseModel):
    ok: bool = True


class AuthMeResponse(BaseModel):
    id: str
    email: str
    username: str | None
    email_verified: bool
    role: str
    status: str


QuotaOverride = Annotated[StrictInt, Field(ge=0, le=2**31 - 1)] | None


class AdminUserUpdateRequest(BaseModel):
    """Omitted fields are left unchanged; an explicit null clears a quota override."""

    model_config = ConfigDict(extra='forbid')

    role: str | None = None
    status: str | None = None
    quota_max_active: QuotaOverride = None
    quota_max_per_day: QuotaOverride = None
    quota_max_batch: QuotaOverride = None

    @field_validator('role')
    @classmethod
    def validate_role(cls, value):
        if value not in ROLES:
            raise ValueError(f'role must be one of {", ".join(ROLES)}')
        return value

    @field_validator('status')
    @classmethod
    def validate_status(cls, value):
        if value not in STATUSES:
            raise ValueError(f'status must be one of {", ".join(STATUSES)}')
        return value


class AdminUserResponse(BaseModel):
    id: str
    email: str
    username: str | None
    role: str
    status: str
    created_at: str
    last_login_at: str | None
    quota_max_active: int | None
    quota_max_per_day: int | None
    quota_max_batch: int | None
    terms_version: str | None = None
    terms_accepted_at: str | None = None
    active_jobs: int
    jobs_24h: int


class AdminUsersResponse(BaseModel):
    users: list[AdminUserResponse]


class AdminRevokeSessionsResponse(BaseModel):
    revoked: int


class AdminUserDeleteResponse(BaseModel):
    deleted: bool
    cancelled_jobs: int


class AdminQuotaConfig(BaseModel):
    max_queued: int
    user_max_active: int
    user_max_per_day: int
    user_max_batch: int
    ip_signups_per_day: int
    ip_submits_per_hour: int
    ip_logins_per_hour: int
    ip_validations_per_hour: int
    otp_sends_per_email_per_hour: int


class AdminOverviewResponse(BaseModel):
    queued: int
    running: int
    failed_24h: int
    completed_24h: int
    workers_online: int
    users_total: int
    users_suspended: int
    quota_config: AdminQuotaConfig
    version: str
