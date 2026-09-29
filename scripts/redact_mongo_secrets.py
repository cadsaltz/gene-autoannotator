"""One-off cleanup: strip NCBI ``api_key=`` values from persisted annotation docs.

Annotation documents written before key redaction may embed NCBI request URLs
(e.g. ``gene_name_source_detail``) that carry the API key, and the frontend
reads these documents directly from MongoDB.

Usage (from the repo root, with MONGO_URI or MONGODB_URI set):

    .venv/bin/python scripts/redact_mongo_secrets.py           # dry run
    .venv/bin/python scripts/redact_mongo_secrets.py --apply   # rewrite docs
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shared.redact import redact_secrets_in  # noqa: E402


def redact_document(document):
    """Return ``(redacted_copy, changed)``; ``_id`` is always preserved as-is."""
    redacted = redact_secrets_in(document)
    if "_id" in document:
        redacted["_id"] = document["_id"]
    return redacted, redacted != document


def find_redactions(documents):
    """Yield ``(original_id, redacted_document)`` for documents that need rewriting."""
    for document in documents:
        redacted, changed = redact_document(document)
        if changed:
            yield document.get("_id"), redacted


def _annotation_collection():
    from backend.annotation_store import AnnotationStoreUnavailable, annotation_store_from_env

    store = annotation_store_from_env()
    try:
        return store._get_collection()
    except (AttributeError, AnnotationStoreUnavailable) as exc:
        raise SystemExit("MONGO_URI (or MONGODB_URI) must point at the annotation store") from exc


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Rewrite matching documents (default: dry run that only reports them).",
    )
    args = parser.parse_args(argv)

    if not (os.getenv("MONGO_URI") or os.getenv("MONGODB_URI")):
        raise SystemExit("MONGO_URI (or MONGODB_URI) is not set")
    collection = _annotation_collection()

    matches = list(find_redactions(collection.find({})))
    print(f"{len(matches)} document(s) contain api_key= values")
    for document_id, _ in matches:
        print(f"  {document_id}")

    if not args.apply:
        if matches:
            print("Dry run: re-run with --apply to rewrite these documents.")
        return 0

    for document_id, redacted in matches:
        collection.replace_one({"_id": document_id}, redacted)
    print(f"Rewrote {len(matches)} document(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
