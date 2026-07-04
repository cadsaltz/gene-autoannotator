import hashlib
import json
import os
import re
import uuid
from datetime import UTC, datetime
from typing import Any

from autoannotation import organisms


class AnnotationStoreUnavailable(RuntimeError):
    """Raised when annotation storage is not configured or reachable."""


def _now_iso():
    return datetime.now(UTC).isoformat()


def _annotation_id(profile_id, normalized_locus):
    # Profile is part of identity because different organisms/strains may use
    # overlapping locus-looking strings.
    return f"{profile_id}:{normalized_locus}"


def _name_annotation_id(profile_id, gene_name):
    normalized_name = str(gene_name).strip().casefold()
    readable_slug = organisms.normalize_identifier(normalized_name) or "gene"
    digest = hashlib.sha256(normalized_name.encode("utf-8")).hexdigest()[:10]
    return f"{profile_id}:name:{readable_slug}-{digest}"


def _extract_generated_at(job, result):
    annotation = result.get("annotation") or {}
    metadata = annotation.get("annotation_metadata") or {}
    return metadata.get("generated_at") or job.get("finished_at") or _now_iso()


def _extract_gene_name(job, result, normalized_locus):
    annotation = result.get("annotation") or {}
    return (
        annotation.get("name")
        or annotation.get("gene_name")
        or job.get("request", {}).get("name")
        or normalized_locus
    )


def _metadata_identity(job, result):
    annotation = result.get("annotation") or {}
    metadata = annotation.get("annotation_metadata") or {}
    profile_id = metadata.get("profile_id")
    normalized_locus = metadata.get("resolved_locus") or metadata.get("gene")
    gene_name = (
        metadata.get("resolved_name")
        or annotation.get("name")
        or job.get("request", {}).get("name")
    )

    if profile_id and normalized_locus:
        return {
            "annotation_id": _annotation_id(profile_id, normalized_locus),
            "profile_id": profile_id,
            "canonical_name": metadata.get("canonical_name"),
            "species_name": metadata.get("species_name"),
            "strain": metadata.get("strain"),
            "normalized_locus": normalized_locus,
            "gene_name": gene_name,
        }
    if profile_id and gene_name:
        return {
            "annotation_id": _name_annotation_id(profile_id, gene_name),
            "profile_id": profile_id,
            "canonical_name": metadata.get("canonical_name"),
            "species_name": metadata.get("species_name"),
            "strain": metadata.get("strain"),
            "normalized_locus": None,
            "gene_name": gene_name,
        }
    return None


def _annotation_identity_from_metadata(job, result):
    identity = _metadata_identity(job, result)
    if identity is not None:
        return identity["annotation_id"], identity["normalized_locus"], identity["gene_name"]

    validation = _validation_for_job(job)
    gene_name = _extract_gene_name(job, result, validation.normalized_locus)
    return (
        _annotation_id(validation.profile_id, validation.normalized_locus),
        validation.normalized_locus,
        gene_name,
    )


def _validation_for_job(job):
    request = job.get("request") or {}
    profile = request.get("profile")
    organism = request.get("organism")
    strain = request.get("strain")
    locus = request.get("locus")

    if profile:
        result = organisms.validate_locus_request(
            profile_identifier=profile,
            locus=locus,
        )
    elif organism:
        result = organisms.validate_locus_request(
            organism_identifier=organism,
            strain_identifier=strain,
            locus=locus,
        )
    else:
        result = organisms.validate_locus_request(
            profile_identifier="mtb-h37rv",
            locus=locus,
        )

    if not result.valid:
        raise ValueError(result.reason or "invalid annotation locus")
    return result


def _version_from_current(current):
    return {
        "version_id": str(uuid.uuid4()),
        "job_id": current["job_id"],
        "generated_at": current["generated_at"],
        "gene_name": current["gene_name"],
        "output_path": current.get("output_path"),
        "result": current["result"],
    }


def _build_document(job, existing=None):
    # Mongo stores one document per profile/locus. The newest successful job is
    # `current`; the previous current result is copied into `versions` so the UI
    # can show history without searching multiple collections.
    result = job.get("result") or {}
    identity = _metadata_identity(job, result)
    if identity is not None:
        annotation_id = identity["annotation_id"]
        profile_id = identity["profile_id"]
        canonical_name = identity["canonical_name"]
        species_name = identity["species_name"]
        strain = identity["strain"]
        normalized_locus = identity["normalized_locus"]
        gene_name = identity["gene_name"] or normalized_locus
    else:
        validation = _validation_for_job(job)
        profile_id = validation.profile_id
        canonical_name = validation.canonical_name
        species_name = validation.species_name
        strain = validation.strain
        normalized_locus = validation.normalized_locus
        gene_name = _extract_gene_name(job, result, normalized_locus)
        annotation_id = _annotation_id(profile_id, normalized_locus)
    generated_at = _extract_generated_at(job, result)
    current = {
        "job_id": job["id"],
        "generated_at": generated_at,
        "gene_name": gene_name,
        "output_path": job.get("output_path") or result.get("output_path"),
        "result": result,
    }
    versions = list((existing or {}).get("versions") or [])
    if existing and existing.get("current"):
        versions.insert(0, _version_from_current(existing["current"]))

    search_text = " ".join(
        str(part)
        for part in (
            profile_id,
            canonical_name,
            species_name,
            strain,
            normalized_locus,
            gene_name,
            json.dumps(result, sort_keys=True),
        )
        if part
    ).lower()

    # Search is intentionally denormalized substring matching for now. It is
    # simple to inspect and test, but not a replacement for indexed full-text
    # search if the annotation library grows.
    return {
        "_id": annotation_id,
        "profile_id": profile_id,
        "canonical_name": canonical_name,
        "species_name": species_name,
        "strain": strain,
        "normalized_locus": normalized_locus,
        "gene_name": gene_name,
        "generated_at": generated_at,
        "current": current,
        "versions": versions,
        "version_count": len(versions),
        "search_text": search_text,
        "updated_at": _now_iso(),
    }


def _public_summary(document):
    return {
        "id": document["_id"],
        "profile_id": document["profile_id"],
        "canonical_name": document["canonical_name"],
        "species_name": document["species_name"],
        "strain": document.get("strain"),
        "normalized_locus": document["normalized_locus"],
        "gene_name": document["gene_name"],
        "generated_at": document["generated_at"],
        "version_count": document.get("version_count", 0),
    }


def _public_detail(document):
    summary = _public_summary(document)
    summary["result"] = document["current"]["result"]
    summary["job_id"] = document["current"]["job_id"]
    summary["output_path"] = document["current"].get("output_path")
    return summary


class DisabledAnnotationStore:
    def health(self):
        return {"status": "unconfigured", "message": "MONGO_URI is not set"}

    def _raise(self):
        raise AnnotationStoreUnavailable("MONGO_URI is not configured")

    def save_completed_job(self, job):
        self._raise()

    def search(self, query, limit=20):
        self._raise()

    def get(self, annotation_id):
        self._raise()

    def get_versions(self, annotation_id):
        self._raise()


class InMemoryAnnotationStore:
    def __init__(self):
        self._documents: dict[str, dict[str, Any]] = {}

    def health(self):
        return {"status": "ok"}

    def save_completed_job(self, job):
        result = job.get("result") or {}
        annotation_id, _, _ = _annotation_identity_from_metadata(job, result)
        existing = self._documents.get(annotation_id)
        document = _build_document(job, existing=existing)
        self._documents[document["_id"]] = document
        return document["_id"]

    def search(self, query, limit=20):
        normalized_query = query.strip().lower()
        if not normalized_query:
            return []
        matches = [
            _public_summary(document)
            for document in self._documents.values()
            if normalized_query in document["search_text"]
        ]
        matches.sort(key=lambda item: item["generated_at"], reverse=True)
        return matches[:limit]

    def get(self, annotation_id):
        document = self._documents.get(annotation_id)
        if document is None:
            return None
        return _public_detail(document)

    def get_versions(self, annotation_id):
        document = self._documents.get(annotation_id)
        if document is None:
            return None
        return list(document.get("versions") or [])


class MongoAnnotationStore:
    def __init__(
        self,
        mongo_uri,
        *,
        database_name="gene_autoannotator",
        collection_name="annotations",
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
                raise AnnotationStoreUnavailable(
                    "pymongo is required for MongoDB annotation storage"
                ) from exc
            self._client = MongoClient(self.mongo_uri, serverSelectionTimeoutMS=1000)
            self._collection = self._client[self.database_name][self.collection_name]
        return self._collection

    def health(self):
        try:
            self._get_collection().database.client.admin.command("ping")
        except Exception as exc:  # noqa: BLE001 - health must report connection errors.
            return {"status": "unavailable", "message": str(exc)}
        return {"status": "ok", "database": self.database_name}

    def save_completed_job(self, job):
        collection = self._get_collection()
        result = job.get("result") or {}
        annotation_id, _, _ = _annotation_identity_from_metadata(job, result)
        existing = collection.find_one({"_id": annotation_id})
        document = _build_document(job, existing=existing)
        collection.replace_one({"_id": document["_id"]}, document, upsert=True)
        return document["_id"]

    def search(self, query, limit=20):
        collection = self._get_collection()
        normalized_query = query.strip()
        if not normalized_query:
            return []
        documents = collection.find(
            {"search_text": {"$regex": re.escape(normalized_query), "$options": "i"}},
            limit=limit,
        )
        return [_public_summary(document) for document in documents]

    def get(self, annotation_id):
        document = self._get_collection().find_one({"_id": annotation_id})
        if document is None:
            return None
        return _public_detail(document)

    def get_versions(self, annotation_id):
        document = self._get_collection().find_one(
            {"_id": annotation_id},
            {"versions": 1},
        )
        if document is None:
            return None
        return list(document.get("versions") or [])


def annotation_store_from_env():
    mongo_uri = os.getenv("MONGO_URI") or os.getenv("MONGODB_URI")
    if not mongo_uri:
        return DisabledAnnotationStore()
    return MongoAnnotationStore(mongo_uri)
