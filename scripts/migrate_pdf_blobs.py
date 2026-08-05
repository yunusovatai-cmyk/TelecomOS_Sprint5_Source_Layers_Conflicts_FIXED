#!/usr/bin/env python3
"""Idempotently copy legacy PDF BYTEA rows to MinIO.

BYTEA is retained by default. --clear-bytea deletes only rows whose MinIO object
was downloaded and verified against the Document SHA-256 in this invocation.
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
backend_path = ROOT / "backend"
if not backend_path.exists() and Path("/app/app").exists():
    backend_path = Path("/app")
sys.path.insert(0, str(backend_path))

from sqlalchemy import select  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.models.document import Document  # noqa: E402
from app.models.pdf_extraction import DocumentBlob, PdfRenderedPage  # noqa: E402
from app.models.project import Project  # noqa: E402,F401 -- register Document FK target
from app.services.object_storage import cleanup_orphan_objects, get_object, put_pdf  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--clear-bytea", action="store_true")
    parser.add_argument("--cleanup-orphans", action="store_true")
    parser.add_argument("--apply-orphan-cleanup", action="store_true")
    parser.add_argument("--orphan-grace-seconds", type=int, default=3600)
    args = parser.parse_args()
    copied = verified = cleared = skipped = failed = 0
    with SessionLocal() as db:
        rows = list(db.execute(select(Document, DocumentBlob).join(
            DocumentBlob, DocumentBlob.document_id == Document.id
        ).where(Document.document_type == "PDF")))
    for document, blob in rows:
        try:
            digest = hashlib.sha256(blob.content).hexdigest()
            if digest != document.sha256 or not blob.content.startswith(b"%PDF-"):
                raise ValueError("legacy blob validation failed")
            if not document.storage_object_key:
                stored = put_pdf(
                    project_id=document.project_id, document_id=document.id,
                    content=blob.content, expected_sha256=document.sha256,
                )
                with SessionLocal() as db:
                    current = db.get(Document, document.id)
                    current.storage_bucket, current.storage_object_key = stored.bucket, stored.object_key
                    current.storage_size_bytes, current.storage_mime_type = stored.size_bytes, stored.mime_type
                    db.commit()
                copied += 1
            else:
                skipped += 1
            with SessionLocal() as db:
                current = db.get(Document, document.id)
                remote = get_object(current.storage_bucket, current.storage_object_key)
                if hashlib.sha256(remote).hexdigest() != current.sha256 or len(remote) != current.storage_size_bytes:
                    raise ValueError("object verification failed")
                verified += 1
                if args.clear_bytea:
                    legacy = db.scalar(select(DocumentBlob).where(DocumentBlob.document_id == current.id))
                    if legacy:
                        db.delete(legacy)
                        db.commit()
                        cleared += 1
        except Exception as exc:
            failed += 1
            print(f"FAILED document={document.id} reason={type(exc).__name__}", file=sys.stderr)
    print(f"copied={copied} verified={verified} skipped={skipped} cleared={cleared} failed={failed}")
    if args.cleanup_orphans or args.apply_orphan_cleanup:
        with SessionLocal() as db:
            referenced = {
                (bucket, key) for bucket, key in db.execute(select(
                    Document.storage_bucket, Document.storage_object_key
                ).where(Document.storage_object_key.is_not(None)))
            }
            referenced.update({
                (bucket, key) for bucket, key in db.execute(select(
                    PdfRenderedPage.bucket, PdfRenderedPage.object_key
                ))
            })
        orphans = cleanup_orphan_objects(
            referenced, grace_seconds=args.orphan_grace_seconds, apply=args.apply_orphan_cleanup,
        )
        action = "removed" if args.apply_orphan_cleanup else "found"
        print(f"orphan_objects_{action}={len(orphans)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
