import logging
import os
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Query, Response, status
from fastapi.middleware.cors import CORSMiddleware

from autoannotation import batch_parse, batch_resolution, organisms, targets
from autoannotation.batch_parse import BatchParseError

from .annotation_store import AnnotationStoreUnavailable, annotation_store_from_env
from .batch_store import BatchStore
from .job_store import JobStore
from .profile_store import (
    DuplicateProfileError,
    InvalidProfileError,
    ProfileStoreUnavailable,
    profile_store_from_env,
)
from .runner import run_annotation_job
from . import regex_gen
from .worker_registry import WorkerRegistry
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
    AnnotationDetailResponse,
    AnnotationJobRequest,
    AnnotationSearchResponse,
    AnnotationVersionsResponse,
    BatchCreateRequest,
    BatchCreateResponse,
    BatchDetailResponse,
    BatchEntryInput,
    BatchValidateRequest,
    BatchValidateResponse,
    JobCreateResponse,
    JobsListResponse,
    JobRecordResponse,
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

if load_dotenv is not None:
    load_dotenv()


log = logging.getLogger(__name__)


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


DEFAULT_DB_PATH = Path("coordinator/jobs.sqlite3")
MAX_BATCH_SIZE = int(os.getenv("MAX_BATCH_SIZE", "2000"))
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
)


def create_app(
    *,
    job_store=None,
    batch_store=None,
    annotation_store=None,
    profile_store=None,
    worker_registry=None,
    run_job=run_annotation_job,
    run_jobs_inline=False,
    start_worker=True,
    worker_api_token=None,
    worker_capacity_required=False,
):
    store = job_store or JobStore(DEFAULT_DB_PATH)
    batches = batch_store or BatchStore(store.db_path)
    workers = worker_registry or WorkerRegistry(store.db_path)
    worker_token = worker_api_token if worker_api_token is not None else os.getenv("WORKER_API_TOKEN")
    lease_seconds = int(os.getenv("LEASE_SECONDS", "31536000"))
    max_attempts = int(os.getenv("MAX_ATTEMPTS", "3"))
    offline_after_seconds = int(os.getenv("WORKER_OFFLINE_SECONDS", "60"))
    annotations = (
        annotation_store
        if annotation_store is not None
        else annotation_store_from_env()
    )
    profiles_store = profile_store or profile_store_from_env()
    worker_lock = threading.Lock()

    def _require_worker_fleet():
        if not worker_capacity_required or run_jobs_inline:
            return
        summary = workers.summary(offline_after_seconds=offline_after_seconds)
        if summary["connected"] == 0 or summary["total_slots"] == 0:
            raise HTTPException(
                status_code=503,
                detail="No workers connected with job capacity.",
            )

    def _maybe_run_jobs_inline():
        # Unit tests only. Production coordinators never execute annotation jobs.
        if run_jobs_inline:
            drain_queue()

    def _require_worker_token(authorization):
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
                    result = run_job(request)
                    store.mark_step(job["id"], "saving_result")
                    output_path = result.get("output_path") if result else None
                    store.mark_completed(job["id"], result or {}, output_path=output_path)
                    completed_job = store.get_job(job["id"])
                    persist_completed_annotation(completed_job)
                except Exception as exc:  # noqa: BLE001 - API must persist job failures.
                    store.mark_failed(job["id"], str(exc))

    @asynccontextmanager
    async def lifespan(app):
        public_url = os.getenv("COORDINATOR_PUBLIC_URL")
        lan_ip = _detect_lan_ip()
        worker_url = public_url or (f"http://{lan_ip}:8000" if lan_ip else None)
        token_status = "set" if worker_token else "not set"
        log.info("Coordinator listening on 0.0.0.0:8000")
        if worker_url:
            log.info(
                "Workers: set COORDINATOR_URL=%s  WORKER_API_TOKEN=%s",
                worker_url,
                token_status,
            )
        else:
            log.info("Workers: set COORDINATOR_URL=<your-lan-ip>:8000  WORKER_API_TOKEN=%s", token_status)
        log.info(
            "Public URL (COORDINATOR_PUBLIC_URL): %s",
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
        _maybe_run_jobs_inline()
        try:
            yield
        finally:
            stop_reaper.set()

    app = FastAPI(title="Gene Autoannotator API", lifespan=lifespan)
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
        try:
            return targets.resolve_annotation_target(
                profile_identifier=_profile_identifier_for_request(request),
                organism_identifier=request.organism,
                strain_identifier=request.strain,
                locus=request.locus,
                name=request.name,
                profile_lookup=_get_profile_for_target if request.profile else None,
                allow_online_name_lookup=False,
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

    def _public_job_record(job):
        public_job = dict(job)
        public_request = dict(public_job.get("request") or {})
        public_request.pop("profile_config", None)
        public_request.pop("ortholog_profile_catalog", None)
        public_job["request"] = public_request
        return public_job

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

    def _preview_batch(request):
        entry_inputs = _entries_from_request(request)
        if len(entry_inputs) > MAX_BATCH_SIZE:
            raise HTTPException(
                status_code=422,
                detail=f"Batch exceeds maximum size of {MAX_BATCH_SIZE}.",
            )
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
        counts = {"queued": 0, "running": 0, "completed": 0, "failed": 0}
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

    @app.get("/health")
    def health():
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

    @app.get("/profiles", response_model=ProfilesResponse)
    def profiles():
        try:
            return {"profiles": profiles_store.list_profiles()}
        except Exception as exc:  # noqa: BLE001 - surface profile storage outages as 503s.
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.post(
        "/profiles",
        response_model=ProfileDetailResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def create_profile(request: ProfilePayload):
        try:
            return profiles_store.create_user_profile(request.model_dump())
        except DuplicateProfileError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except InvalidProfileError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except ProfileStoreUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.get("/profiles/{profile_id}", response_model=ProfileDetailResponse)
    def get_profile(profile_id: str):
        try:
            profile = profiles_store.get_profile(profile_id)
        except Exception as exc:  # noqa: BLE001 - surface profile storage outages as 503s.
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        if profile is None:
            raise HTTPException(status_code=404, detail="Profile not found")
        return profile

    @app.put("/profiles/{profile_id}", response_model=ProfileDetailResponse)
    def update_profile(profile_id: str, request: ProfilePayload):
        try:
            profile = profiles_store.update_user_profile(profile_id, request.model_dump())
        except InvalidProfileError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except ProfileStoreUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        if profile is None:
            raise HTTPException(status_code=404, detail="Profile not found")
        return profile

    @app.delete("/profiles/{profile_id}")
    def delete_profile(profile_id: str):
        try:
            deleted = profiles_store.delete_user_profile(profile_id)
        except InvalidProfileError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except ProfileStoreUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        if not deleted:
            raise HTTPException(status_code=404, detail="Profile not found")
        return {"deleted": True}

    @app.post("/validate")
    def validate_locus(request: ValidationRequest):
        target = _resolve_target_for_request(request)
        return target.to_preflight_dict()

    @app.post("/regex/from-examples")
    def regex_from_examples_endpoint(request: RegexFromExamplesRequest):
        try:
            return regex_gen.regex_from_examples(request.examples)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/regex/from-description")
    def regex_from_description_endpoint(request: RegexFromDescriptionRequest):
        try:
            return regex_gen.regex_from_description(request.description)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except regex_gen.RegexGenerationError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.post("/batches/validate", response_model=BatchValidateResponse)
    def validate_batch(request: BatchValidateRequest):
        try:
            entries, summary = _preview_batch(request)
        except BatchParseError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"summary": summary, "entries": entries}

    @app.post(
        "/batches",
        response_model=BatchCreateResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def create_batch(request: BatchCreateRequest, background_tasks: BackgroundTasks):
        try:
            entries, summary = _preview_batch(request)
        except BatchParseError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        ready_entries = [entry for entry in entries if entry["status"] == "ready"]
        if not ready_entries:
            raise HTTPException(status_code=422, detail="No ready entries to queue.")

        _reject_unresolvable_ortholog_override(request.ortholog_override)
        _require_worker_fleet()

        skipped = [entry for entry in entries if entry["status"] != "ready"]
        batch = batches.create_batch(
            profile=request.profile,
            organism=request.organism,
            strain=request.strain,
            options=_batch_options_from_request(request),
            input_summary=summary,
        )

        job_ids = []
        for entry in ready_entries:
            job_request = _job_request_for_batch_entry(request, entry)
            target = _resolve_target_for_request(job_request)
            invalid_target_detail = _invalid_target_detail(target)
            if invalid_target_detail is not None:
                continue
            stored_request = _stored_request_for_target(job_request, target)
            job = store.create_job(stored_request, batch_id=batch["id"])
            job_ids.append(job["id"])

        if not job_ids:
            raise HTTPException(status_code=422, detail="No ready entries to queue.")

        _maybe_run_jobs_inline()

        return {
            "batch_id": batch["id"],
            "job_ids": job_ids,
            "skipped": skipped,
            "summary": summary,
        }

    @app.get("/batches/{batch_id}", response_model=BatchDetailResponse)
    def get_batch(batch_id: str):
        batch = batches.get_batch(batch_id)
        if batch is None:
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
    def create_job(request: AnnotationJobRequest, background_tasks: BackgroundTasks):
        _reject_unresolvable_ortholog_override(request.ortholog_override)
        target = _resolve_target_for_request(request)
        _reject_invalid_target(target)
        stored_request = _stored_request_for_target(request, target)
        _require_worker_fleet()
        job = store.create_job(stored_request)
        _maybe_run_jobs_inline()
        if run_jobs_inline:
            job = store.get_job(job["id"])
        return {"job_id": job["id"], "status": job["status"]}

    @app.get("/jobs", response_model=JobsListResponse)
    def list_jobs(order: str = "newest", batch_id: str | None = None):
        normalized_order = order if order in {"newest", "queue"} else "newest"
        return {
            "jobs": [
                _public_job_record(job)
                for job in store.list_jobs(
                    order=normalized_order,
                    batch_id=batch_id,
                )
            ],
            "queue": store.queue_summary(),
        }

    @app.delete("/jobs/history")
    def clear_jobs_history():
        return {"deleted": store.clear_finished_jobs()}

    @app.get("/jobs/{job_id}", response_model=JobRecordResponse)
    def get_job(job_id: str):
        job = store.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        return _public_job_record(job)

    @app.get("/jobs/{job_id}/result")
    def get_job_result(job_id: str):
        job = store.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        if job["status"] != "completed":
            raise HTTPException(status_code=409, detail="Job is not completed")
        return job["result"]

    @app.get("/annotations/search", response_model=AnnotationSearchResponse)
    def search_annotations(query: str, limit: int = Query(default=20, ge=1, le=100)):
        try:
            matches = annotations.search(query, limit=limit)
        except Exception as exc:  # noqa: BLE001 - surface storage outages as 503s.
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return {"query": query, "matches": matches}

    @app.get("/annotations/{annotation_id}", response_model=AnnotationDetailResponse)
    def get_annotation(annotation_id: str):
        try:
            annotation = annotations.get(annotation_id)
        except Exception as exc:  # noqa: BLE001 - surface storage outages as 503s.
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        if annotation is None:
            raise HTTPException(status_code=404, detail="Annotation not found")
        return annotation

    @app.get(
        "/annotations/{annotation_id}/versions",
        response_model=AnnotationVersionsResponse,
    )
    def get_annotation_versions(annotation_id: str):
        try:
            versions = annotations.get_versions(annotation_id)
        except Exception as exc:  # noqa: BLE001 - surface storage outages as 503s.
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        if versions is None:
            raise HTTPException(status_code=404, detail="Annotation not found")
        return {"annotation_id": annotation_id, "versions": versions}

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

        # Use the live claim request for this worker so claims are not blocked by a
        # stale heartbeat that still shows free_slots=0 between heartbeats.
        ready_slots: list[int] = []
        for peer in workers.list_workers(offline_after_seconds=offline_after_seconds):
            if peer["state"] != "ready":
                continue
            slots = request.free_slots if peer["id"] == worker_id else peer["free_slots"]
            if slots > 0:
                ready_slots.append(slots)
        if not ready_slots:
            return Response(status_code=204)
        if request.free_slots < max(ready_slots):
            return Response(status_code=204)
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
        store.mark_step(job_id, request.current_step)
        store.renew_lease(job_id, lease_seconds=lease_seconds)
        return Response(status_code=204)

    @app.post("/jobs/{job_id}/complete", status_code=204)
    def complete_job(
        job_id: str, request: JobComplete, authorization: str | None = Header(default=None)
    ):
        _require_worker_token(authorization)
        output_path = request.result.get("output_path")
        if store.complete_if_running(job_id, request.result, output_path=output_path):
            persist_completed_annotation(store.get_job(job_id))
        return Response(status_code=204)

    @app.post("/jobs/{job_id}/fail", status_code=204)
    def fail_job_route(
        job_id: str, request: JobFail, authorization: str | None = Header(default=None)
    ):
        _require_worker_token(authorization)
        store.fail_job(job_id, request.error, retryable=request.retryable, max_attempts=max_attempts)
        return Response(status_code=204)

    @app.post("/workers/{worker_id}/drain", status_code=204)
    def drain_worker(worker_id: str, authorization: str | None = Header(default=None)):
        _require_worker_token(authorization)
        if not workers.set_state(worker_id, "draining"):
            raise HTTPException(status_code=404, detail="Worker not registered")
        return Response(status_code=204)

    @app.get("/workers")
    def list_workers():
        return {"workers": workers.list_workers(offline_after_seconds=offline_after_seconds)}

    @app.get("/coordinator-info")
    def coordinator_info():
        return {
            "worker_url": os.getenv("COORDINATOR_PUBLIC_URL"),
            "version": os.getenv("APP_VERSION", "dev"),
        }

    return app


app = create_app(worker_capacity_required=True)
