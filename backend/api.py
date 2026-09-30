import asyncio
import logging
import os
import threading
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Query, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from autoannotation import batch_parse, batch_resolution, gene_names, organisms, targets
from autoannotation.batch_parse import BatchParseError

from .access import is_admin
from .alerts import AlertConfig, AlertLoop
from .annotation_store import AnnotationStoreUnavailable, annotation_store_from_env
from .audit_store import DEFAULT_LIST_LIMIT, MAX_LIST_LIMIT, AuditStore, mask_email
from .backup import BackupConfig, backup_task, retention_task
from .auth import (
    OTP_TTL_SECONDS,
    SESSION_COOKIE_NAME,
    SESSION_TTL_SECONDS,
    hash_secret,
    new_otp_code,
    new_session_token,
)
from .auth_store import AuthStore
from .batch_store import BatchStore
from .client_ip import client_ip
from .db_path import DEFAULT_DB_PATH, LEGACY_DB_PATH  # noqa: F401 - re-exported
from .db_path import migrate_legacy_db_if_needed as _migrate_legacy_db_if_needed
from . import email_sender
from .job_store import JobStore
from .quotas import (
    QuotaConfig,
    QuotaExceeded,
    check_batch_size,
    check_submission,
    daily_window_start,
    effective_limits,
)
from .profile_store import (
    DEFAULT_PROFILES_DIR,
    DuplicateProfileError,
    InvalidProfileError,
    ProfileStoreUnavailable,
    profile_store_from_env,
)
from .rate_limits import (
    DAY_SECONDS,
    HOUR_SECONDS,
    RATE_LIMIT_DEFAULTS,
    RateLimited,
    RateLimiter,
    rate_limit_from_env,
)
from .runner import run_annotation_job
from . import regex_gen
from .worker_registry import WorkerRegistry
from shared.redact import redact_secrets_in, redact_url_secrets
from shared.worker_contract import (
    ClaimRequest,
    HeartbeatResponse,
    JobComplete,
    JobFail,
    JobProgress,
    WorkerHeartbeat,
    WorkerRegister,
    WorkerRegisterResponse,
)
from .schemas import (
    AdminOverviewResponse,
    AdminRevokeSessionsResponse,
    AdminUserDeleteResponse,
    AdminUserResponse,
    AdminUsersResponse,
    AdminUserUpdateRequest,
    AnnotationDetailResponse,
    AnnotationJobRequest,
    AnnotationSearchResponse,
    AnnotationVersionsResponse,
    AuthLoginRequest,
    AuthMeResponse,
    AuthOkResponse,
    AuthSignupRequest,
    AuthVerifyRequest,
    BatchCreateRequest,
    BatchCreateResponse,
    BatchDetailResponse,
    BatchEntryInput,
    BatchValidateRequest,
    BatchValidateResponse,
    JobCreateResponse,
    JobsListResponse,
    JobRecordResponse,
    QueueStatusResponse,
    ProfileDetailResponse,
    ProfilePayload,
    ProfilesResponse,
    RegexFromDescriptionRequest,
    RegexFromExamplesRequest,
    ValidationRequest,
)

# FastAPI wrapper around the existing annotator. It is deliberately thin: jobs
# run in this Python process, SQLite stores queue state, and optional MongoDB
# storage keeps searchable annotation history.
try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - dependency is optional at import time.
    load_dotenv = None

# Repo-root `.env` only (never `*.example` / `backend.env.example`). Path is
# anchored to this file so starting uvicorn from another cwd still works.
_REPO_ROOT = Path(__file__).resolve().parents[1]
_ENV_FILE = _REPO_ROOT / ".env"
if load_dotenv is not None:
    load_dotenv(_ENV_FILE)


log = logging.getLogger(__name__)
log.info(
    "Loaded env from %s (exists=%s); EMAIL_BACKEND=%s",
    _ENV_FILE,
    _ENV_FILE.is_file(),
    os.getenv("EMAIL_BACKEND", "console"),
)


def _detect_lan_ip():
    import socket

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError:
        return None


def _regex_model_health():
    from autoannotation import models

    model = os.getenv("AUTOANNOTATION_REGEX_MODEL") or models.MODEL_REGEX
    if not model:
        return {
            "status": "unconfigured",
            "model": None,
            "message": "No regex model configured",
        }

    try:
        import ollama

        list_result = ollama.list()
        entries = list_result.get("models", []) if isinstance(list_result, dict) else list_result
        installed = set()
        for entry in entries:
            if isinstance(entry, dict):
                name = entry.get("model") or entry.get("name")
            else:
                name = getattr(entry, "model", None) or getattr(entry, "name", None)
            if name:
                installed.add(name)
        if model in installed:
            return {"status": "ok", "model": model}
        return {
            "status": "unavailable",
            "model": model,
            "message": f"Model {model!r} is not installed in Ollama",
        }
    except Exception as exc:  # noqa: BLE001 - health reports Ollama failures without failing /health.
        return {"status": "unavailable", "model": model, "message": str(exc)}


MAX_BATCH_SIZE = int(os.getenv("MAX_BATCH_SIZE", "2000"))
# Keep in sync with TERMS_VERSION in frontend/lib/legal.js.
DEFAULT_TERMS_VERSION = "draft-2026-09"
# Six hours is long enough for an HPC allocation to finish one annotation while
# still recovering a job whose Slurm allocation died without failing it. Live
# workers keep their leases fresh through progress reports and heartbeats.
DEFAULT_LEASE_SECONDS = 21600
SERVER_CACHE_DIR = "./.cache"
SERVER_OUTPUT_DIR = "gen_json"
SERVER_GENE_NAME_CACHE = gene_names.DEFAULT_GENE_NAME_CACHE_DIR
_SERVER_PATH_UPDATES = {
    "cache_dir": SERVER_CACHE_DIR,
    "output_dir": SERVER_OUTPUT_DIR,
    "gene_name_cache": SERVER_GENE_NAME_CACHE,
}
TRUE_VALUES = {"1", "true", "yes", "on"}
FALSE_VALUES = {"0", "false", "no", "off"}
DEFAULT_CORS_ORIGINS = (
    "http://localhost:3000",
    "http://127.0.0.1:3000",
)
DEFAULT_CORS_ORIGIN_REGEX = (
    r"^https?://("
    r"localhost|"
    r"127\.0\.0\.1|"
    r"10(?:\.\d{1,3}){3}|"
    r"192\.168(?:\.\d{1,3}){2}|"
    r"172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2}"
    r"):3000$"
)
PROFILE_CONFIG_FIELDS = (
    "profile_id",
    "canonical_name",
    "species_name",
    "strain",
    "synonyms",
    "species_synonyms",
    "strain_synonyms",
    "locus_regex",
    "search_terms",
    "target_patterns",
    "off_target_patterns",
    "excluded_species_patterns",
    "kegg_organism_code",
    "kegg_locus_regex",
    "go_resolution_enabled",
)
QUOTA_OVERRIDE_FIELDS = ("quota_max_active", "quota_max_per_day", "quota_max_batch")


def _env_flag(name, default):
    raw = (os.getenv(name) or "").strip().lower()
    if raw in TRUE_VALUES:
        return True
    if raw in FALSE_VALUES:
        return False
    return default


def _server_owned_job_request(request: AnnotationJobRequest) -> AnnotationJobRequest:
    return request.model_copy(update=_SERVER_PATH_UPDATES)


def _auth_expires_at(ttl_seconds: int) -> str:
    return (datetime.now(UTC) + timedelta(seconds=ttl_seconds)).isoformat()


def _owned_or_admin(record: dict, user: dict) -> bool:
    return is_admin(user) or record.get("submitted_by_user_id") == user["id"]


_ANNOTATION_ADMIN_FIELDS = ("job_id", "output_path")


def _annotation_for_user(record: dict, user: dict) -> dict:
    if is_admin(user):
        return record
    return {key: value for key, value in record.items() if key not in _ANNOTATION_ADMIN_FIELDS}


class SubmissionsUnavailable(Exception):
    """Non-admin view of a missing worker fleet; must not reveal fleet state."""

    code = "unavailable"
    message = "The service isn't accepting new jobs right now. Please try again later."


class SubmissionsPaused(SubmissionsUnavailable):
    code = "paused"
    message = "New submissions are paused. Please try again later."


def _submissions_paused() -> bool:
    return _env_flag("SUBMISSIONS_PAUSED", False)


def create_app(
    *,
    job_store=None,
    auth_store=None,
    batch_store=None,
    annotation_store=None,
    profile_store=None,
    worker_registry=None,
    run_job=run_annotation_job,
    run_jobs_inline=False,
    start_worker=True,
    worker_api_token=None,
    worker_capacity_required=False,
    rate_limiter=None,
    audit_store=None,
):
    store = job_store or JobStore(_migrate_legacy_db_if_needed(DEFAULT_DB_PATH))
    auth = auth_store or AuthStore(store.db_path)
    batches = batch_store or BatchStore(store.db_path)
    workers = worker_registry or WorkerRegistry(store.db_path)
    limiter = rate_limiter or RateLimiter(store.db_path)
    audit = audit_store or AuditStore(store.db_path)
    worker_token = worker_api_token if worker_api_token is not None else os.getenv("WORKER_API_TOKEN")
    # An HPC-only deploy has no warm worker to satisfy the gate, so
    # WORKER_CAPACITY_REQUIRED=0 must be able to turn it off at deploy time.
    capacity_required = _env_flag("WORKER_CAPACITY_REQUIRED", worker_capacity_required)
    lease_seconds = int(os.getenv("LEASE_SECONDS", str(DEFAULT_LEASE_SECONDS)))
    max_attempts = int(os.getenv("MAX_ATTEMPTS", "3"))
    offline_after_seconds = int(os.getenv("WORKER_OFFLINE_SECONDS", "60"))
    terms_version = (os.getenv("TERMS_VERSION") or "").strip() or DEFAULT_TERMS_VERSION
    annotations = (
        annotation_store
        if annotation_store is not None
        else annotation_store_from_env()
    )
    profiles_store = profile_store or profile_store_from_env()
    worker_lock = threading.Lock()
    # Quota checks count existing rows, so check-then-insert must be atomic or
    # concurrent submissions can all pass the same check.
    submission_lock = threading.Lock()
    # The last-admin guard counts admins before mutating, so two admins
    # demoting each other concurrently could otherwise both pass it. When both
    # are needed, take admin_lock first.
    admin_lock = threading.Lock()

    def _require_still_active(user: dict):
        # Call under submission_lock: suspend and delete cancel jobs under the
        # same lock, so a submission cannot slip in after their cancel.
        current = auth.get_user(user["id"])
        if current is None or current["status"] != "active":
            raise HTTPException(status_code=403, detail="Account suspended")

    def _reject_if_paused(user: dict):
        if _submissions_paused() and not is_admin(user):
            raise SubmissionsPaused()

    def _require_worker_fleet(user: dict):
        if not capacity_required or run_jobs_inline:
            return
        summary = workers.summary(offline_after_seconds=offline_after_seconds)
        if summary["connected"] == 0 or summary["total_slots"] == 0:
            if not is_admin(user):
                raise SubmissionsUnavailable()
            raise HTTPException(
                status_code=503,
                detail="No workers connected with job capacity.",
            )

    def _maybe_run_jobs_inline():
        # Unit tests only. Production backends never execute annotation jobs.
        if run_jobs_inline:
            drain_queue()

    def _require_worker_token(authorization):
        require_token = _env_flag("REQUIRE_WORKER_API_TOKEN", False)
        if require_token and not worker_token:
            raise HTTPException(
                status_code=503,
                detail="WORKER_API_TOKEN is required but not configured.",
            )
        if not worker_token:
            return
        expected = f"Bearer {worker_token}"
        if authorization != expected:
            raise HTTPException(status_code=401, detail="Invalid or missing worker token")

    def persist_completed_annotation(job):
        # Annotation history/search is a secondary persistence path. A Mongo
        # outage should be visible on the job but should not erase a completed
        # annotation result or mark the LLM run itself as failed.
        try:
            annotations.save_completed_job(job)
            store.mark_annotation_persisted(job["id"])
        except AnnotationStoreUnavailable:
            store.mark_annotation_error(job["id"], "MONGO_URI is not configured")
        except Exception as exc:  # noqa: BLE001 - expose persistence failures on the job.
            store.mark_annotation_error(job["id"], str(exc))

    def drain_queue():
        # One process-local drain loop is enough because JobStore also refuses
        # to claim a second running job. Multi-process deployments still need a
        # more explicit worker design before being treated as durable.
        with worker_lock:
            while True:
                job = store.claim_next_queued_job()
                if job is None:
                    return
                try:
                    request = AnnotationJobRequest(**job["request"])
                    target = _resolve_target_for_request(request)
                    invalid_target_detail = _invalid_target_detail(target)
                    if invalid_target_detail is not None:
                        raise ValueError(invalid_target_detail)
                    result = redact_secrets_in(run_job(request))
                    store.mark_step(job["id"], "saving_result")
                    output_path = result.get("output_path") if result else None
                    store.mark_completed(job["id"], result or {}, output_path=output_path)
                    completed_job = store.get_job(job["id"])
                    persist_completed_annotation(completed_job)
                except Exception as exc:  # noqa: BLE001 - API must persist job failures.
                    store.mark_failed(job["id"], redact_url_secrets(str(exc)))

    @asynccontextmanager
    async def lifespan(app):
        public_url = os.getenv("BACKEND_PUBLIC_URL")
        lan_ip = _detect_lan_ip()
        worker_url = public_url or (f"http://{lan_ip}:8000" if lan_ip else None)
        token_status = "set" if worker_token else "not set"
        log.info("Backend listening on 0.0.0.0:8000")
        if worker_url:
            log.info(
                "Workers: set BACKEND_URL=%s  WORKER_API_TOKEN=%s",
                worker_url,
                token_status,
            )
        else:
            log.info(
                "Workers: set BACKEND_URL=<your-lan-ip>:8000  WORKER_API_TOKEN=%s",
                token_status,
            )
        log.info(
            "Public URL (BACKEND_PUBLIC_URL): %s",
            public_url or "not set",
        )

        stop_reaper = threading.Event()

        def reaper_loop():
            while not stop_reaper.wait(30):
                # Never let a transient error (e.g. a momentary SQLite lock)
                # kill the reaper thread permanently and stop all lease recovery.
                try:
                    store.requeue_expired_leases(max_attempts=max_attempts)
                except Exception:  # noqa: BLE001 - keep the reaper alive across failures.
                    log.exception("Lease reaper iteration failed")

        reaper = threading.Thread(target=reaper_loop, daemon=True)
        reaper.start()

        alert_config = AlertConfig.from_env(offline_after_seconds=offline_after_seconds)
        alert_loop = None
        if alert_config.enabled:
            alert_loop = AlertLoop(
                store=store,
                workers=workers,
                recipients=auth.list_active_admin_emails,
                config=alert_config,
            )
            alert_loop.start()
        else:
            log.info("Admin alerts disabled (ALERT_CHECK_SECONDS<=0)")
        app.state.alert_loop = alert_loop

        backup_config = BackupConfig.from_env()
        backup_loop = None
        if backup_config.backups_enabled:
            backup_loop = backup_task(
                config=backup_config,
                db_path=store.db_path,
                profiles_dir=getattr(profiles_store, "directory", None)
                or os.getenv("PROFILES_DIR")
                or DEFAULT_PROFILES_DIR,
            )
            backup_loop.start()
        elif backup_config.interval_seconds <= 0:
            log.info("Control-plane backups disabled (BACKUP_INTERVAL_SECONDS<=0)")
        else:
            log.info("Control-plane backups disabled (MONGO_URI is not set)")
        app.state.backup_loop = backup_loop

        retention_loop = retention_task(
            config=backup_config, store=store, auth=auth, limiter=limiter, audit=audit
        )
        retention_loop.start()
        app.state.retention_loop = retention_loop

        _maybe_run_jobs_inline()
        try:
            yield
        finally:
            stop_reaper.set()
            for loop in (alert_loop, backup_loop, retention_loop):
                if loop is not None:
                    await asyncio.to_thread(loop.stop, timeout=5)

    app = FastAPI(title="Gene Autoannotator API", lifespan=lifespan)
    app.state.audit_store = audit
    app.state.alert_loop = None
    app.state.backup_loop = None
    app.state.retention_loop = None
    app.state.submission_lock = submission_lock
    cors_origins = [
        origin.strip()
        for origin in os.getenv("CORS_ORIGINS", ",".join(DEFAULT_CORS_ORIGINS)).split(",")
        if origin.strip()
    ]
    cors_origin_regex = os.getenv("CORS_ORIGIN_REGEX", DEFAULT_CORS_ORIGIN_REGEX).strip()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_origin_regex=cors_origin_regex or None,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(QuotaExceeded)
    async def quota_exceeded_handler(_request: Request, exc: QuotaExceeded):
        return JSONResponse(status_code=429, content={"detail": exc.message, "code": exc.code})

    @app.exception_handler(SubmissionsUnavailable)
    async def submissions_unavailable_handler(_request: Request, exc: SubmissionsUnavailable):
        return JSONResponse(status_code=503, content={"detail": exc.message, "code": exc.code})

    def _rate_check(bucket, key, window_seconds, env_name, message):
        return (bucket, key or "unknown", window_seconds, rate_limit_from_env(env_name), message)

    def _enforce_rate_limits(*checks):
        active = [check for check in checks if check[3] > 0]
        # Peek at every limit before recording any, so a request rejected by
        # one limit is not charged against the others.
        for bucket, key, window_seconds, limit, message in active:
            if not limiter.would_allow(bucket, key, window_seconds, limit):
                raise RateLimited(message)
        for bucket, key, window_seconds, limit, message in active:
            if not limiter.hit(bucket, key, window_seconds, limit):
                raise RateLimited(message)

    def _signup_ip_check(request: Request):
        return _rate_check(
            "signup",
            client_ip(request),
            DAY_SECONDS,
            "IP_SIGNUPS_PER_DAY",
            "Too many sign-ups from your network today. Please try again later.",
        )

    def _login_ip_check(request: Request):
        return _rate_check(
            "login_ip",
            client_ip(request),
            HOUR_SECONDS,
            "IP_LOGINS_PER_HOUR",
            "Too many sign-in attempts from your network this hour. Please try again later.",
        )

    def _otp_send_check(email: str):
        return _rate_check(
            "otp_send",
            email.strip().lower(),
            HOUR_SECONDS,
            "OTP_SENDS_PER_EMAIL_PER_HOUR",
            "Too many sign-in codes requested for this email. Please try again later.",
        )

    def _audit(request: Request, action: str, actor_user_id: str | None, **fields):
        audit.record(action=action, actor_user_id=actor_user_id, ip=client_ip(request), **fields)

    def _enforce_submit_limit(request: Request, user: dict):
        if is_admin(user):
            return
        _enforce_rate_limits(
            _rate_check(
                "submit",
                client_ip(request),
                HOUR_SECONDS,
                "IP_SUBMITS_PER_HOUR",
                "Too many submissions from your network this hour. Please try again later.",
            )
        )

    def resource_snapshot():
        try:
            import psutil
        except ImportError:
            return {"status": "unavailable", "message": "psutil is not installed"}

        memory = psutil.virtual_memory()
        return {
            "status": "ok",
            "cpu_percent": psutil.cpu_percent(interval=None),
            "memory_total_bytes": memory.total,
            "memory_used_bytes": memory.used,
            "memory_available_bytes": memory.available,
            "memory_percent": memory.percent,
        }

    def _profile_identifier_for_request(request):
        if request.profile or not request.organism or not request.locus:
            return request.profile
        result = organisms.validate_locus_request(
            organism_identifier=request.organism,
            strain_identifier=request.strain,
            locus=request.locus,
        )
        if result.valid and result.profile_id:
            return result.profile_id
        return None

    def _get_profile_for_target(profile_id):
        try:
            return profiles_store.get_profile(profile_id)
        except Exception as exc:  # noqa: BLE001 - profile storage failures are service outages.
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    def _resolve_target_for_request(request):
        allow_online_name_lookup = getattr(request, "allow_online_name_lookup", False)
        try:
            return targets.resolve_annotation_target(
                profile_identifier=_profile_identifier_for_request(request),
                organism_identifier=request.organism,
                strain_identifier=request.strain,
                locus=request.locus,
                name=request.name,
                profile_lookup=_get_profile_for_target if request.profile else None,
                allow_online_name_lookup=allow_online_name_lookup,
                locus_regex=request.locus_regex,
                search_terms=request.search_terms,
                target_patterns=request.target_patterns,
                off_target_patterns=request.off_target_patterns,
                excluded_species_patterns=request.excluded_species_patterns,
            )
        except organisms.UnknownOrganismError as exc:
            raise HTTPException(status_code=404, detail="Profile not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    def _serialize_profile_fields(profile):
        custom = getattr(profile, "custom_fields", ()) or ()
        custom_fields = [
            field_def.to_dict() if hasattr(field_def, "to_dict") else dict(field_def)
            for field_def in custom
        ]
        raw_default = getattr(profile, "default_field_ortholog", ()) or ()
        if isinstance(raw_default, dict):
            default_field_ortholog = {
                key: bool(value) for key, value in raw_default.items()
            }
        else:
            default_field_ortholog = {
                key: bool(value) for key, value in raw_default
            }
        return custom_fields, default_field_ortholog

    def _profile_config_from_target(target):
        config = {
            field: getattr(target.profile, field)
            for field in PROFILE_CONFIG_FIELDS
        }
        for field, value in config.items():
            if isinstance(value, tuple):
                config[field] = list(value)
        custom_fields, default_field_ortholog = _serialize_profile_fields(target.profile)
        config["custom_fields"] = custom_fields
        config["annotation_fields"] = list(custom_fields)
        config["default_field_ortholog"] = default_field_ortholog
        config["source"] = target.profile_source
        return config

    def _ortholog_profile_catalog():
        """Snapshot every kegg-coded profile so workers can select ortholog sources
        without a live profile-store round-trip."""
        catalog = []
        try:
            profiles = profiles_store.list_profiles()
        except Exception:  # noqa: BLE001 - catalog is best-effort enrichment
            return catalog
        for document in profiles:
            kegg = document.get("kegg_organism_code")
            if not kegg:
                continue
            catalog.append({
                "profile_id": document.get("profile_id"),
                "canonical_name": document.get("canonical_name"),
                "species_name": document.get("species_name"),
                "strain": document.get("strain"),
                "synonyms": list(document.get("synonyms") or []),
                "species_synonyms": list(document.get("species_synonyms") or []),
                "strain_synonyms": list(document.get("strain_synonyms") or []),
                "locus_regex": document.get("locus_regex") or "",
                "search_terms": list(document.get("search_terms") or []),
                "target_patterns": list(document.get("target_patterns") or []),
                "off_target_patterns": list(document.get("off_target_patterns") or []),
                "excluded_species_patterns": list(
                    document.get("excluded_species_patterns") or []
                ),
                "kegg_organism_code": kegg,
                "custom_fields": list(
                    document.get("custom_fields")
                    or document.get("annotation_fields")
                    or []
                ),
                "default_field_ortholog": dict(
                    document.get("default_field_ortholog") or {}
                ),
            })
        return catalog

    def _stored_request_for_target(request, target):
        stored_request = request.model_dump()
        if target.profile_source != "ad_hoc":
            stored_request["profile"] = target.profile.profile_id
            stored_request["organism"] = None
            stored_request["strain"] = None
        stored_request["target_preflight"] = target.to_preflight_dict()
        # Attach the resolved profile snapshot for named/local profiles so
        # workers use the local store document, not code-only defaults.
        if request.profile or target.profile_source == "local":
            stored_request["profile_config"] = _profile_config_from_target(target)
        stored_request["ortholog_profile_catalog"] = _ortholog_profile_catalog()
        return stored_request

    def _invalid_target_detail(target):
        preflight = target.to_preflight_dict()
        if preflight["valid"]:
            return None
        return next(
            (
                warning["message"]
                for warning in preflight["warnings"]
                if warning["code"] == targets.LOCUS_SCHEMA_MISMATCH
            ),
            "The target could not be submitted.",
        )

    def _reject_invalid_target(target):
        detail = _invalid_target_detail(target)
        if detail is None:
            return
        raise HTTPException(status_code=422, detail=detail)

    def _reject_unresolvable_ortholog_override(override):
        # Resolve via the same local profile store the UI edits, then fall
        # back to code catalog profiles for CLI-only organisms.
        if override is None:
            return
        profile_id = override.profile_id
        stored = _get_profile_for_target(profile_id)
        if stored is not None:
            return
        try:
            organisms.resolve_profile(profile_id)
        except organisms.UnknownOrganismError as exc:
            raise HTTPException(
                status_code=422,
                detail=f"Unknown ortholog override profile: {profile_id}",
            ) from exc

    def _public_job_record(job, user, emails=None):
        public_job = dict(job)
        public_request = dict(public_job.get("request") or {})
        public_request.pop("profile_config", None)
        public_request.pop("ortholog_profile_catalog", None)
        public_job["request"] = public_request
        if is_admin(user):
            owner = public_job.get("submitted_by_user_id")
            if emails is None:
                emails = auth.emails_by_ids([owner])
            public_job["submitted_by_email"] = emails.get(owner)
        else:
            public_job.pop("submitted_by_user_id", None)
            public_job.pop("submitted_by_email", None)
            public_job.pop("output_path", None)
        return redact_secrets_in(public_job)

    def _visible_job_or_404(job_id, user):
        # 404 rather than 403 so job ids owned by others are indistinguishable
        # from ids that do not exist.
        job = store.get_job(job_id)
        if job is None or not _owned_or_admin(job, user):
            raise HTTPException(status_code=404, detail="Job not found")
        return job

    def _entries_from_request(request):
        if request.entries:
            return list(request.entries)
        if request.raw_text:
            parsed = batch_parse.parse_batch_text(request.raw_text)
            return [BatchEntryInput(**item) for item in parsed]
        raise BatchParseError("No genes found.")

    def _resolve_batch_profile(request):
        if request.profile:
            profile_payload = _get_profile_for_target(request.profile)
            if profile_payload is None:
                raise HTTPException(status_code=404, detail="Profile not found")
            return organisms.profile_from_mapping(profile_payload)
        return targets.build_ad_hoc_profile(
            request.organism,
            request.strain,
            locus_regex=request.locus_regex,
            search_terms=request.search_terms,
            target_patterns=request.target_patterns,
            off_target_patterns=request.off_target_patterns,
            excluded_species_patterns=request.excluded_species_patterns,
        )

    def _preview_batch(request, user):
        entry_inputs = _entries_from_request(request)
        if len(entry_inputs) > MAX_BATCH_SIZE:
            raise HTTPException(
                status_code=422,
                detail=f"Batch exceeds maximum size of {MAX_BATCH_SIZE}.",
            )
        check_batch_size(user=user, entry_count=len(entry_inputs), config=QuotaConfig.from_env())
        profile = _resolve_batch_profile(request)
        entries = []
        for line_number, entry_input in enumerate(entry_inputs, start=1):
            raw_input = entry_input.input or entry_input.locus or entry_input.name or ""
            entries.append(
                batch_resolution.resolve_batch_entry(
                    profile,
                    line=line_number,
                    raw_input=raw_input,
                    submitted_locus=entry_input.locus,
                    submitted_name=entry_input.name,
                    allow_online_name_lookup=request.allow_online_name_lookup,
                    selected_locus=entry_input.selected_locus,
                )
            )
        entries = batch_resolution.apply_deduplication(
            entries,
            profile_id=profile.profile_id,
        )
        summary = batch_resolution.summarize_entries(entries)
        return entries, summary

    def _batch_options_from_request(request):
        return request.model_dump(exclude={"entries", "raw_text"})

    def _batch_queue_summary(batch_id):
        counts = {"queued": 0, "running": 0, "completed": 0, "failed": 0, "cancelled": 0}
        for job in store.list_jobs_by_batch(batch_id):
            counts[job["status"]] = counts.get(job["status"], 0) + 1
        return counts

    def _job_request_for_batch_entry(request, entry):
        return AnnotationJobRequest(
            profile=request.profile,
            organism=request.organism,
            strain=request.strain,
            locus=entry["resolved_locus"],
            name=entry["resolved_name"],
            cache_dir=request.cache_dir,
            output_dir=request.output_dir,
            gene_name_cache=request.gene_name_cache,
            allow_online_name_lookup=request.allow_online_name_lookup,
            refresh_gene_name_cache=request.refresh_gene_name_cache,
            cache_supplied_name=request.cache_supplied_name,
            locus_regex=request.locus_regex,
            search_terms=request.search_terms,
            target_patterns=request.target_patterns,
            off_target_patterns=request.off_target_patterns,
            excluded_species_patterns=request.excluded_species_patterns,
            allow_ortholog_fallback=request.allow_ortholog_fallback,
            ortholog_override=request.ortholog_override,
        )

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    def _session_cookie_secure():
        return _env_flag("SESSION_COOKIE_SECURE", False)

    def _set_session_cookie(response: Response, token: str):
        response.set_cookie(
            key=SESSION_COOKIE_NAME,
            value=token,
            httponly=True,
            samesite="lax",
            secure=_session_cookie_secure(),
            max_age=SESSION_TTL_SECONDS,
            path="/",
        )

    def _clear_session_cookie(response: Response):
        response.delete_cookie(
            key=SESSION_COOKIE_NAME,
            path="/",
            httponly=True,
            secure=_session_cookie_secure(),
            samesite="lax",
        )

    def _issue_login_code(request: Request, *, user: dict, email: str, purpose: str):
        code = new_otp_code()
        auth.create_login_code(
            email=email,
            purpose=purpose,
            code_hash=hash_secret(code),
            expires_at=_auth_expires_at(OTP_TTL_SECONDS),
        )
        try:
            email_sender.send_login_code_email(to_email=email, code=code)
        except Exception as exc:  # noqa: BLE001 - surface delivery failures to the client
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Could not send login code: {exc}",
            ) from exc
        _audit(
            request,
            "login_code_sent",
            user["id"],
            target_type="user",
            target_id=user["id"],
            details={"purpose": purpose},
        )

    def require_user(request: Request, response: Response) -> dict:
        token = request.cookies.get(SESSION_COOKIE_NAME)
        if not token:
            raise HTTPException(status_code=401, detail="Authentication required")
        token_hash = hash_secret(token)
        user = auth.get_session_user(token_hash)
        if user is None or not user["email_verified"]:
            raise HTTPException(status_code=401, detail="Authentication required")
        if user["status"] != "active":
            raise HTTPException(status_code=403, detail="Account suspended")
        auth.touch_session(token_hash, _auth_expires_at(SESSION_TTL_SECONDS))
        # Refresh browser Max-Age so sliding 90-day sessions stay in sync with SQLite.
        _set_session_cookie(response, token)
        return user

    def require_admin(user: dict = Depends(require_user)) -> dict:
        if not is_admin(user):
            raise HTTPException(status_code=403, detail="Admin access required")
        return user

    @app.get("/health")
    def health(_user: dict = Depends(require_admin)):
        try:
            job_store_health = store.health()
        except Exception as exc:  # noqa: BLE001 - health reports failures.
            job_store_health = {"status": "unavailable", "message": str(exc)}

        try:
            annotation_health = annotations.health()
        except Exception as exc:  # noqa: BLE001 - health reports failures.
            annotation_health = {"status": "unavailable", "message": str(exc)}

        try:
            profile_health = profiles_store.health()
        except Exception as exc:  # noqa: BLE001 - health reports failures.
            profile_health = {"status": "unavailable", "message": str(exc)}

        return {
            "status": "ok",
            "stores": {
                "jobs": job_store_health,
                "annotations": annotation_health,
                "profiles": profile_health,
            },
            "queue": store.queue_summary(),
            "workers": workers.summary(offline_after_seconds=offline_after_seconds),
            "resources": resource_snapshot(),
            "regex_model": _regex_model_health(),
        }

    # Signup and login answer 200 either way so responses never reveal whether
    # an address is registered or suspended. Rate limits are charged before the
    # account lookup for the same reason.
    @app.post("/auth/signup", response_model=AuthOkResponse)
    def auth_signup(body: AuthSignupRequest, request: Request):
        email = str(body.email)
        _enforce_rate_limits(_signup_ip_check(request), _otp_send_check(email))
        user = auth.get_user_by_email(email)
        if user is None:
            user = auth.create_user(
                email=email, username=body.username, terms_version=terms_version
            )
            _audit(
                request, "signup", user["id"], target_type="user", target_id=user["id"],
                details={"terms_version": terms_version},
            )
        if user["status"] != "active":
            return AuthOkResponse()
        _issue_login_code(request, user=user, email=email, purpose="signup")
        return AuthOkResponse()

    @app.post("/auth/login", response_model=AuthOkResponse)
    def auth_login(body: AuthLoginRequest, request: Request):
        email = str(body.email)
        _enforce_rate_limits(_login_ip_check(request), _otp_send_check(email))
        user = auth.get_user_by_email(email)
        if user is None or user["status"] != "active":
            return AuthOkResponse()
        _issue_login_code(request, user=user, email=email, purpose="login")
        return AuthOkResponse()

    @app.post("/auth/verify", response_model=AuthOkResponse)
    def auth_verify(body: AuthVerifyRequest, request: Request, response: Response):
        email = str(body.email)
        code_hash = hash_secret(body.code)
        consumed = auth.consume_login_code(email=email, code_hash=code_hash)
        if consumed is None:
            auth.register_failed_code_attempt(email=email, code_hash=code_hash)
            raise HTTPException(status_code=401, detail="Invalid or expired code")
        user = auth.get_user_by_email(email)
        if user is None:
            raise HTTPException(status_code=401, detail="Invalid or expired code")
        if user["status"] != "active":
            raise HTTPException(status_code=403, detail="Account suspended")
        auth.mark_email_verified(user["id"])
        # Signup codes are only issued after accept_terms, so verifying one
        # proves the address owner consented; accounts created before consent
        # was required get it recorded here.
        if consumed["purpose"] == "signup" and not user["terms_version"]:
            auth.record_terms_acceptance(user["id"], terms_version)
        token = new_session_token()
        auth.create_session(
            user_id=user["id"],
            token_hash=hash_secret(token),
            expires_at=_auth_expires_at(SESSION_TTL_SECONDS),
            ip=client_ip(request),
        )
        auth.mark_login(user["id"])
        _audit(request, "login", user["id"], target_type="user", target_id=user["id"])
        _set_session_cookie(response, token)
        return AuthOkResponse()

    @app.get("/auth/me", response_model=AuthMeResponse)
    def auth_me(_user: dict = Depends(require_user)):
        return AuthMeResponse(
            id=_user["id"],
            email=_user["email"],
            username=_user["username"],
            email_verified=_user["email_verified"],
            role=_user["role"],
            status=_user["status"],
        )

    @app.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
    def auth_logout(request: Request, response: Response):
        token = request.cookies.get(SESSION_COOKIE_NAME)
        if token:
            token_hash = hash_secret(token)
            user = auth.get_session_user(token_hash)
            auth.delete_session(token_hash)
            if user is not None:
                _audit(request, "logout", user["id"], target_type="user", target_id=user["id"])
        _clear_session_cookie(response)

    @app.get("/profiles", response_model=ProfilesResponse)
    def profiles(_user: dict = Depends(require_user)):
        try:
            return {"profiles": profiles_store.list_profiles()}
        except Exception as exc:  # noqa: BLE001 - surface profile storage outages as 503s.
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.post(
        "/profiles",
        response_model=ProfileDetailResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def create_profile(
        request: ProfilePayload, http_request: Request, _user: dict = Depends(require_admin)
    ):
        try:
            profile = profiles_store.create_user_profile(request.model_dump())
        except DuplicateProfileError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except InvalidProfileError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except ProfileStoreUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        _audit(
            http_request,
            "profile_create",
            _user["id"],
            target_type="profile",
            target_id=profile.get("profile_id") or request.profile_id,
        )
        return profile

    @app.get("/profiles/{profile_id}", response_model=ProfileDetailResponse)
    def get_profile(profile_id: str, _user: dict = Depends(require_user)):
        try:
            profile = profiles_store.get_profile(profile_id)
        except Exception as exc:  # noqa: BLE001 - surface profile storage outages as 503s.
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        if profile is None:
            raise HTTPException(status_code=404, detail="Profile not found")
        return profile

    @app.put("/profiles/{profile_id}", response_model=ProfileDetailResponse)
    def update_profile(
        profile_id: str,
        request: ProfilePayload,
        http_request: Request,
        _user: dict = Depends(require_admin),
    ):
        try:
            profile = profiles_store.update_user_profile(profile_id, request.model_dump())
        except InvalidProfileError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except ProfileStoreUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        if profile is None:
            raise HTTPException(status_code=404, detail="Profile not found")
        _audit(
            http_request, "profile_update", _user["id"], target_type="profile", target_id=profile_id
        )
        return profile

    @app.delete("/profiles/{profile_id}")
    def delete_profile(
        profile_id: str, http_request: Request, _user: dict = Depends(require_admin)
    ):
        try:
            deleted = profiles_store.delete_user_profile(profile_id)
        except InvalidProfileError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except ProfileStoreUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        if not deleted:
            raise HTTPException(status_code=404, detail="Profile not found")
        _audit(
            http_request, "profile_delete", _user["id"], target_type="profile", target_id=profile_id
        )
        return {"deleted": True}

    @app.post("/validate")
    def validate_locus(request: ValidationRequest, _user: dict = Depends(require_user)):
        target = _resolve_target_for_request(request)
        return target.to_preflight_dict()

    @app.post("/regex/from-examples")
    def regex_from_examples_endpoint(
        request: RegexFromExamplesRequest, _user: dict = Depends(require_admin)
    ):
        try:
            return regex_gen.regex_from_examples(request.examples)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/regex/from-description")
    def regex_from_description_endpoint(
        request: RegexFromDescriptionRequest, _user: dict = Depends(require_admin)
    ):
        try:
            return regex_gen.regex_from_description(request.description)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except regex_gen.RegexGenerationError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.post("/batches/validate", response_model=BatchValidateResponse)
    def validate_batch(request: BatchValidateRequest, _user: dict = Depends(require_user)):
        try:
            entries, summary = _preview_batch(request, _user)
        except BatchParseError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"summary": summary, "entries": entries}

    @app.post(
        "/batches",
        response_model=BatchCreateResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def create_batch(
        request: BatchCreateRequest,
        background_tasks: BackgroundTasks,
        http_request: Request,
        _user: dict = Depends(require_user),
    ):
        _reject_if_paused(_user)
        request = request.model_copy(update=_SERVER_PATH_UPDATES)
        try:
            entries, summary = _preview_batch(request, _user)
        except BatchParseError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        ready_entries = [entry for entry in entries if entry["status"] == "ready"]
        if not ready_entries:
            raise HTTPException(status_code=422, detail="No ready entries to queue.")

        _reject_unresolvable_ortholog_override(request.ortholog_override)
        _require_worker_fleet(_user)

        skipped = [entry for entry in entries if entry["status"] != "ready"]
        stored_requests = []
        for entry in ready_entries:
            job_request = _job_request_for_batch_entry(request, entry)
            target = _resolve_target_for_request(job_request)
            if _invalid_target_detail(target) is not None:
                continue
            stored_requests.append(_stored_request_for_target(job_request, target))

        if not stored_requests:
            raise HTTPException(status_code=422, detail="No ready entries to queue.")

        with submission_lock:
            check_submission(
                user=_user,
                job_count=len(stored_requests),
                store=store,
                config=QuotaConfig.from_env(),
            )
            _require_still_active(_user)
            _enforce_submit_limit(http_request, _user)
            batch = batches.create_batch(
                profile=request.profile,
                organism=request.organism,
                strain=request.strain,
                options=_batch_options_from_request(request),
                input_summary=summary,
                submitted_by_user_id=_user["id"],
            )
            job_ids = [
                store.create_job(
                    stored_request,
                    batch_id=batch["id"],
                    submitted_by_user_id=batch["submitted_by_user_id"],
                )["id"]
                for stored_request in stored_requests
            ]
        _audit(
            http_request,
            "batch_submit",
            _user["id"],
            target_type="batch",
            target_id=batch["id"],
            details={"job_count": len(job_ids)},
        )

        _maybe_run_jobs_inline()

        return {
            "batch_id": batch["id"],
            "job_ids": job_ids,
            "skipped": skipped,
            "summary": summary,
        }

    @app.get("/batches/{batch_id}", response_model=BatchDetailResponse)
    def get_batch(batch_id: str, _user: dict = Depends(require_user)):
        batch = batches.get_batch(batch_id)
        if batch is None or not _owned_or_admin(batch, _user):
            raise HTTPException(status_code=404, detail="Batch not found")
        return {
            "id": batch["id"],
            "status": batch["status"],
            "profile": batch["profile"],
            "organism": batch["organism"],
            "strain": batch["strain"],
            "created_at": batch["created_at"],
            "summary": batch["input_summary"],
            "queue": _batch_queue_summary(batch_id),
        }

    @app.post(
        "/jobs",
        response_model=JobCreateResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def create_job(
        request: AnnotationJobRequest,
        background_tasks: BackgroundTasks,
        http_request: Request,
        _user: dict = Depends(require_user),
    ):
        _reject_if_paused(_user)
        request = _server_owned_job_request(request)
        _reject_unresolvable_ortholog_override(request.ortholog_override)
        target = _resolve_target_for_request(request)
        _reject_invalid_target(target)
        stored_request = _stored_request_for_target(request, target)
        _require_worker_fleet(_user)
        with submission_lock:
            check_submission(user=_user, job_count=1, store=store, config=QuotaConfig.from_env())
            _require_still_active(_user)
            _enforce_submit_limit(http_request, _user)
            job = store.create_job(stored_request, submitted_by_user_id=_user["id"])
        _audit(http_request, "job_submit", _user["id"], target_type="job", target_id=job["id"])
        _maybe_run_jobs_inline()
        if run_jobs_inline:
            job = store.get_job(job["id"])
        return {"job_id": job["id"], "status": job["status"]}

    # Exclude unset fields so admin-only keys popped for non-admins are omitted
    # rather than serialized as null.
    @app.get(
        "/jobs",
        response_model=JobsListResponse,
        response_model_exclude_unset=True,
    )
    def list_jobs(
        order: str = "newest",
        batch_id: str | None = None,
        _user: dict = Depends(require_user),
    ):
        normalized_order = order if order in {"newest", "queue"} else "newest"
        owner_filter = None if is_admin(_user) else _user["id"]
        jobs = store.list_jobs(order=normalized_order, batch_id=batch_id, user_id=owner_filter)
        emails = (
            auth.emails_by_ids(job.get("submitted_by_user_id") for job in jobs)
            if is_admin(_user)
            else None
        )
        return {
            "jobs": [_public_job_record(job, _user, emails) for job in jobs],
            "queue": store.queue_summary(user_id=owner_filter),
        }

    @app.delete("/jobs/history")
    def clear_jobs_history(_user: dict = Depends(require_admin)):
        return {"deleted": store.clear_finished_jobs()}

    @app.get("/jobs/queue-summary")
    def queued_jobs_summary(authorization: str | None = Header(default=None)):
        # Peek only: status transitions are reserved for fleet claim endpoints.
        _require_worker_token(authorization)
        return {"queued": store.count_queued_jobs()}

    @app.get("/jobs/queue-status", response_model=QueueStatusResponse)
    def queue_status(_user: dict = Depends(require_user)):
        config = QuotaConfig.from_env()
        limits = effective_limits(_user, config)
        queued = store.count_queued_jobs()
        max_batch = limits["max_batch"]
        paused = _submissions_paused()
        return {
            "queued": queued,
            "accepting": is_admin(_user) or (not paused and config.accepting(queued)),
            "paused": paused,
            "your_active": store.count_active_for_user(_user["id"]),
            "your_active_limit": limits["max_active"],
            "your_today": store.count_created_since_for_user(_user["id"], daily_window_start()),
            "your_daily_limit": limits["max_per_day"],
            "batch_limit": MAX_BATCH_SIZE if max_batch is None else min(max_batch, MAX_BATCH_SIZE),
        }

    @app.get(
        "/jobs/{job_id}",
        response_model=JobRecordResponse,
        response_model_exclude_unset=True,
    )
    def get_job(job_id: str, _user: dict = Depends(require_user)):
        return _public_job_record(_visible_job_or_404(job_id, _user), _user)

    @app.post(
        "/jobs/{job_id}/cancel",
        response_model=JobRecordResponse,
        response_model_exclude_unset=True,
    )
    def cancel_job(job_id: str, http_request: Request, _user: dict = Depends(require_user)):
        job = _visible_job_or_404(job_id, _user)
        by = "user" if job.get("submitted_by_user_id") == _user["id"] else "admin"
        if store.cancel_job(job_id, by=by) is None:
            raise HTTPException(status_code=409, detail="Job is already finished")
        _audit(
            http_request,
            "job_cancel",
            _user["id"],
            target_type="job",
            target_id=job_id,
            details={"previous_status": job["status"], "by": by},
        )
        return _public_job_record(store.get_job(job_id), _user)

    @app.get("/jobs/{job_id}/result")
    def get_job_result(job_id: str, _user: dict = Depends(require_user)):
        job = _visible_job_or_404(job_id, _user)
        if job["status"] != "completed":
            raise HTTPException(status_code=409, detail="Job is not completed")
        return redact_secrets_in(job["result"])

    @app.get("/annotations/search", response_model=AnnotationSearchResponse)
    def search_annotations(
        query: str,
        limit: int = Query(default=20, ge=1, le=100),
        _user: dict = Depends(require_user),
    ):
        try:
            matches = annotations.search(query, limit=limit)
        except Exception as exc:  # noqa: BLE001 - surface storage outages as 503s.
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return {"query": query, "matches": redact_secrets_in(matches)}

    @app.get("/annotations/{annotation_id}", response_model=AnnotationDetailResponse)
    def get_annotation(annotation_id: str, _user: dict = Depends(require_user)):
        try:
            annotation = annotations.get(annotation_id)
        except Exception as exc:  # noqa: BLE001 - surface storage outages as 503s.
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        if annotation is None:
            raise HTTPException(status_code=404, detail="Annotation not found")
        return redact_secrets_in(_annotation_for_user(annotation, _user))

    @app.get(
        "/annotations/{annotation_id}/versions",
        response_model=AnnotationVersionsResponse,
    )
    def get_annotation_versions(annotation_id: str, _user: dict = Depends(require_user)):
        try:
            versions = annotations.get_versions(annotation_id)
        except Exception as exc:  # noqa: BLE001 - surface storage outages as 503s.
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        if versions is None:
            raise HTTPException(status_code=404, detail="Annotation not found")
        visible = [_annotation_for_user(version, _user) for version in versions]
        return {"annotation_id": annotation_id, "versions": redact_secrets_in(visible)}

    @app.post("/workers/register", response_model=WorkerRegisterResponse)
    def register_worker(request: WorkerRegister, authorization: str | None = Header(default=None)):
        _require_worker_token(authorization)
        worker_id = workers.register(request.model_dump())
        return {"worker_id": worker_id}

    @app.post("/workers/{worker_id}/heartbeat", response_model=HeartbeatResponse)
    def worker_heartbeat(
        worker_id: str, request: WorkerHeartbeat, authorization: str | None = Header(default=None)
    ):
        _require_worker_token(authorization)
        if not workers.heartbeat(worker_id, request.model_dump()):
            raise HTTPException(status_code=404, detail="Worker not registered")
        # A heartbeat proves the worker is alive, so its running jobs are not
        # stranded and the reaper should not requeue them mid-run.
        store.renew_worker_leases(worker_id, lease_seconds=lease_seconds)
        required_version = os.getenv("REQUIRED_WORKER_VERSION")
        worker = workers.get(worker_id, offline_after_seconds=offline_after_seconds)
        drain = worker is not None and worker["state"] == "draining"
        return {"required_version": required_version, "drain": drain}

    @app.post("/workers/{worker_id}/claim")
    def claim_job(
        worker_id: str, request: ClaimRequest, authorization: str | None = Header(default=None)
    ):
        _require_worker_token(authorization)
        if request.free_slots <= 0:
            return Response(status_code=204)
        worker = workers.get(worker_id, offline_after_seconds=offline_after_seconds)
        if worker is None or worker["state"] != "ready":
            return Response(status_code=204)

        # Any ready worker that says it has a free slot may claim, and the
        # worker's own request decides that rather than its last heartbeat,
        # which can be stale. The atomic store claim is what prevents double
        # assignment; preferring the worker with the most free slots would
        # starve single-slot HPC workers whenever an idle laptop is registered.
        # Keep every fleet assignment on the store's serialized claim path.
        job = store.assign_job_to_worker(worker_id, lease_seconds=lease_seconds)
        if job is None:
            return Response(status_code=204)
        # Send the full stored request, including profile_config for user/ad-hoc
        # profiles. AnnotationJobRequest ignores extra stored keys such as
        # target_preflight, so the worker rebuilds the model directly. (Serializing
        # via ClaimResponse would drop profile_config, which has exclude=True.)
        return {
            "job_id": job["id"],
            "request": job["request"],
            "lease_expires_at": job["lease_expires_at"],
        }

    @app.patch("/jobs/{job_id}/progress", status_code=204)
    def report_progress(
        job_id: str, request: JobProgress, authorization: str | None = Header(default=None)
    ):
        _require_worker_token(authorization)
        job = store.get_job(job_id)
        if job is not None and job["status"] == "cancelled":
            return JSONResponse(
                status_code=409, content={"detail": "Job cancelled", "cancelled": True}
            )
        store.mark_step(
            job_id,
            request.current_step,
            phase=request.phase,
            sections_done=request.sections_done,
            sections_total=request.sections_total,
            pass_name=request.pass_name,
        )
        store.renew_lease(job_id, lease_seconds=lease_seconds)
        return Response(status_code=204)

    @app.post("/jobs/{job_id}/complete", status_code=204)
    def complete_job(
        job_id: str, request: JobComplete, authorization: str | None = Header(default=None)
    ):
        _require_worker_token(authorization)
        # Workers older than the NCBI key redaction fix can still send key-bearing URLs.
        result = redact_secrets_in(request.result)
        output_path = result.get("output_path")
        if store.complete_if_running(
            job_id, result, output_path=output_path, worker_id=request.worker_id
        ):
            persist_completed_annotation(store.get_job(job_id))
        else:
            log.info(
                "Ignored complete for job %s from worker %s: not running on that worker",
                job_id,
                request.worker_id,
            )
        return Response(status_code=204)

    @app.post("/jobs/{job_id}/fail", status_code=204)
    def fail_job_route(
        job_id: str, request: JobFail, authorization: str | None = Header(default=None)
    ):
        _require_worker_token(authorization)
        applied = store.fail_job(
            job_id,
            redact_url_secrets(request.error),
            retryable=request.retryable,
            max_attempts=max_attempts,
            worker_id=request.worker_id,
        )
        if not applied:
            log.info(
                "Ignored fail for job %s from worker %s: not running on that worker",
                job_id,
                request.worker_id,
            )
        return Response(status_code=204)

    @app.post("/workers/{worker_id}/drain", status_code=204)
    def drain_worker(worker_id: str, authorization: str | None = Header(default=None)):
        _require_worker_token(authorization)
        if not workers.set_state(worker_id, "draining"):
            raise HTTPException(status_code=404, detail="Worker not registered")
        return Response(status_code=204)

    @app.delete("/workers/{worker_id}", status_code=204)
    def deregister_worker(worker_id: str, authorization: str | None = Header(default=None)):
        # Ephemeral Slurm workers call this on exit so a finished allocation
        # does not linger in the fleet view until the offline window elapses.
        _require_worker_token(authorization)
        if not workers.delete(worker_id):
            raise HTTPException(status_code=404, detail="Worker not registered")
        return Response(status_code=204)

    @app.get("/workers")
    def list_workers(_user: dict = Depends(require_admin)):
        return {"workers": workers.list_workers(offline_after_seconds=offline_after_seconds)}

    def _admin_user_rows(users):
        counts = store.user_job_counts([user["id"] for user in users], daily_window_start())
        return [
            {
                **user,
                "active_jobs": counts[user["id"]]["active"],
                "jobs_24h": counts[user["id"]]["since"],
            }
            for user in users
        ]

    def _user_or_404(user_id):
        user = auth.get_user(user_id)
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")
        return user

    def _guard_last_admin(target, after):
        if is_admin(target) and not is_admin(after) and auth.count_admins() <= 1:
            raise HTTPException(status_code=409, detail="Cannot remove the last admin")

    @app.get("/admin/users", response_model=AdminUsersResponse)
    def admin_list_users(query: str | None = None, _user: dict = Depends(require_admin)):
        return {"users": _admin_user_rows(auth.list_users(query=query))}

    @app.patch("/admin/users/{user_id}", response_model=AdminUserResponse)
    def admin_update_user(
        user_id: str,
        body: AdminUserUpdateRequest,
        request: Request,
        _user: dict = Depends(require_admin),
    ):
        provided = body.model_fields_set
        with admin_lock:
            target = _user_or_404(user_id)
            role = body.role if "role" in provided else target["role"]
            new_status = body.status if "status" in provided else target["status"]
            _guard_last_admin(target, {"role": role, "status": new_status})

            def audit_change(action, details):
                _audit(
                    request, action, _user["id"],
                    target_type="user", target_id=user_id, details=details,
                )

            if role != target["role"]:
                auth.set_role(user_id, role)
                audit_change("role_change", {"from": target["role"], "to": role})
            if new_status != target["status"]:
                details = {"from": target["status"], "to": new_status}
                with submission_lock:
                    auth.set_status(user_id, new_status)
                    try:
                        if new_status == "suspended":
                            details["cancelled_jobs"] = None
                            details["cancelled_jobs"] = store.cancel_active_for_user(user_id)
                    finally:
                        audit_change("status_change", details)
                if new_status == "suspended":
                    audit_change("sessions_revoked", {"count": auth.revoke_sessions(user_id)})
            quota_changes = {
                field: {"from": target[field], "to": getattr(body, field)}
                for field in QUOTA_OVERRIDE_FIELDS
                if field in provided and getattr(body, field) != target[field]
            }
            if quota_changes:
                quotas = {field: target[field] for field in QUOTA_OVERRIDE_FIELDS}
                quotas.update({field: change["to"] for field, change in quota_changes.items()})
                auth.set_quota_overrides(
                    user_id,
                    max_active=quotas["quota_max_active"],
                    max_per_day=quotas["quota_max_per_day"],
                    max_batch=quotas["quota_max_batch"],
                )
                audit_change("quota_change", quota_changes)
            return _admin_user_rows([auth.get_user(user_id)])[0]

    @app.post(
        "/admin/users/{user_id}/revoke-sessions", response_model=AdminRevokeSessionsResponse
    )
    def admin_revoke_sessions(
        user_id: str, request: Request, _user: dict = Depends(require_admin)
    ):
        _user_or_404(user_id)
        revoked = auth.revoke_sessions(user_id)
        _audit(
            request, "sessions_revoked", _user["id"],
            target_type="user", target_id=user_id, details={"count": revoked},
        )
        return {"revoked": revoked}

    @app.delete("/admin/users/{user_id}", response_model=AdminUserDeleteResponse)
    def admin_delete_user(user_id: str, request: Request, _user: dict = Depends(require_admin)):
        with admin_lock:
            target = _user_or_404(user_id)
            _guard_last_admin(target, None)
            revoked = auth.revoke_sessions(user_id)
            cancelled = None
            anonymized = {"jobs": None, "batches": None}
            with submission_lock:
                auth.delete_user(user_id)
                try:
                    limiter.forget_key(target["email"].strip().lower())
                    cancelled = store.cancel_active_for_user(user_id)
                    anonymized = store.anonymize_user(user_id)
                finally:
                    _audit(
                        request, "user_delete", _user["id"],
                        target_type="user", target_id=user_id,
                        details={
                            "email": mask_email(target["email"]),
                            "cancelled_jobs": cancelled,
                            "anonymized_jobs": anonymized["jobs"],
                            "anonymized_batches": anonymized["batches"],
                            "sessions_revoked": revoked,
                        },
                    )
        return {"deleted": True, "cancelled_jobs": cancelled}

    @app.get("/admin/overview", response_model=AdminOverviewResponse)
    def admin_overview(_user: dict = Depends(require_admin)):
        queue = store.queue_summary()
        finished = store.counts_since(daily_window_start())
        users_by_status = auth.count_users_by_status()
        return {
            "queued": queue["queued"],
            "running": queue["running"],
            "failed_24h": finished["failed"],
            "completed_24h": finished["completed"],
            "workers_online": workers.summary(offline_after_seconds=offline_after_seconds)[
                "connected"
            ],
            "users_total": sum(users_by_status.values()),
            "users_suspended": users_by_status["suspended"],
            "quota_config": {
                **asdict(QuotaConfig.from_env()),
                **{name.lower(): rate_limit_from_env(name) for name in RATE_LIMIT_DEFAULTS},
            },
            "version": os.getenv("APP_VERSION", "dev"),
        }

    @app.get("/admin/audit")
    def list_audit_events(
        limit: int = Query(default=DEFAULT_LIST_LIMIT, ge=1, le=MAX_LIST_LIMIT),
        action: str | None = None,
        user_id: str | None = None,
        _user: dict = Depends(require_admin),
    ):
        return {"events": audit.list(limit=limit, action=action, user_id=user_id)}

    @app.get("/backend-info")
    def backend_info(_user: dict = Depends(require_admin)):
        return {
            "worker_url": os.getenv("BACKEND_PUBLIC_URL"),
            "version": os.getenv("APP_VERSION", "dev"),
        }

    return app


app = create_app(worker_capacity_required=True)
