from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone

from sqlalchemy import delete, select

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.asset import Asset
from app.models.document import Document
from app.models.pdf_extraction import PdfPageText, PdfPoleEvidence, PdfProcessingJob, PdfRenderedPage
from app.models.pole_entity import PoleEntitySource, PoleRelationship
from app.services.object_storage import get_object, put_rendered_page
from app.services.pdf_conflict_engine import compare_pdf_to_kmz
from app.services.pdf_pole_extractor import extract_evidence, extract_native_pages, render_pdf_page
from app.services.pole_entity_resolution import commit_relationships, resolve_pole_entities


ASSET_POLE_ID_RE = re.compile(r"\b(\d{9})\b")


class JobCancelled(Exception):
    pass


def _update(job_id: uuid.UUID, *, progress: int, stage: str) -> None:
    with SessionLocal() as db:
        job = db.get(PdfProcessingJob, job_id)
        if job is None or job.cancel_requested:
            raise JobCancelled()
        job.progress = progress
        job.stage = stage
        job.heartbeat_at = datetime.now(timezone.utc)
        db.commit()


def _load_content(document: Document) -> bytes:
    if not document.storage_bucket or not document.storage_object_key:
        raise ValueError("PDF object metadata is missing.")
    content = get_object(document.storage_bucket, document.storage_object_key)
    if len(content) != document.storage_size_bytes or not content.startswith(b"%PDF-"):
        raise ValueError("Stored PDF validation failed.")
    import hashlib
    if hashlib.sha256(content).hexdigest() != document.sha256:
        raise ValueError("Stored PDF SHA-256 mismatch.")
    return content


def process_job(job_id: uuid.UUID) -> None:
    with SessionLocal() as db:
        job = db.scalar(select(PdfProcessingJob).where(PdfProcessingJob.id == job_id).with_for_update())
        if job is None or job.status != "QUEUED":
            return
        if job.cancel_requested:
            job.status, job.stage = "CANCELLED", "CANCELLED"
            job.finished_at = datetime.now(timezone.utc)
            db.commit()
            return
        job.status, job.stage, job.progress = "RUNNING", "DOWNLOADING", 5
        job.attempts += 1
        job.started_at = job.started_at or datetime.now(timezone.utc)
        job.heartbeat_at = datetime.now(timezone.utc)
        document_id, project_id = job.document_id, job.project_id
        db.commit()

    try:
        with SessionLocal() as db:
            document = db.scalar(select(Document).where(
                Document.id == document_id, Document.project_id == project_id,
            ))
            if document is None:
                raise ValueError("PDF document not found.")
            content = _load_content(document)

        _update(job_id, progress=15, stage="EXTRACTING")
        pages = extract_native_pages(content, max_pages=settings.pdf_max_pages, max_words=settings.pdf_max_words)
        evidence = extract_evidence(pages, max_evidence=settings.pdf_max_evidence)
        _update(job_id, progress=45, stage="PERSISTING")

        with SessionLocal() as db:
            document = db.scalar(select(Document).where(
                Document.id == document_id, Document.project_id == project_id,
            ).with_for_update())
            if document is None:
                raise ValueError("PDF document not found.")
            evidence_ids = list(db.scalars(select(PdfPoleEvidence.id).where(PdfPoleEvidence.document_id == document_id)))
            if evidence_ids:
                db.execute(delete(PoleRelationship).where(PoleRelationship.source_evidence_id.in_(evidence_ids)))
                db.execute(delete(PoleEntitySource).where(
                    PoleEntitySource.source_type == "PDF_EVIDENCE", PoleEntitySource.source_id.in_(evidence_ids),
                ))
            db.execute(delete(PdfPoleEvidence).where(PdfPoleEvidence.document_id == document_id))
            db.execute(delete(PdfPageText).where(PdfPageText.document_id == document_id))
            assets = list(db.scalars(select(Asset).where(Asset.project_id == project_id)))
            assets_by_pole_id = {
                pole_id: asset for asset in assets for pole_id in ASSET_POLE_ID_RE.findall(asset.name or "")
            }
            db.add_all([PdfPageText(
                document_id=document_id, page_number=page.page_number, raw_text=page.raw_text,
                page_width=page.page_width, page_height=page.page_height,
            ) for page in pages])
            db.add_all([PdfPoleEvidence(
                document_id=document_id, page_number=item.page_number, evidence_type=item.evidence_type,
                pole_id=item.pole_id, external_eid=item.external_eid, from_pole_id=item.from_pole_id,
                to_pole_id=item.to_pole_id, span_length_ft=item.span_length_ft, raw_text=item.raw_text,
                bbox_json=json.dumps(item.bbox), confidence=item.confidence, review_status="OPEN",
                matched_asset_id=(assets_by_pole_id.get(item.pole_id or item.from_pole_id or "").id
                                  if assets_by_pole_id.get(item.pole_id or item.from_pole_id or "") else None),
            ) for item in evidence])
            document.processing_status = "PROCESSING"
            db.commit()

        _update(job_id, progress=55, stage="RENDERING")
        for index, page in enumerate(pages, start=1):
            png = render_pdf_page(content, page.page_number, max_pixels=settings.pdf_max_render_pixels)
            stored = put_rendered_page(
                project_id=project_id, document_id=document_id, page_number=page.page_number, content=png,
            )
            with SessionLocal() as db:
                record = db.scalar(select(PdfRenderedPage).where(
                    PdfRenderedPage.document_id == document_id,
                    PdfRenderedPage.page_number == page.page_number,
                ))
                if record is None:
                    record = PdfRenderedPage(document_id=document_id, page_number=page.page_number)
                    db.add(record)
                record.bucket, record.object_key = stored.bucket, stored.object_key
                record.size_bytes, record.sha256 = stored.size_bytes, stored.sha256
                db.commit()
            if index % 10 == 0:
                _update(job_id, progress=min(75, 55 + int(20 * index / max(1, len(pages)))), stage="RENDERING")

        _update(job_id, progress=80, stage="RESOLVING")
        with SessionLocal() as db:
            resolve_pole_entities(db, project_id, document_id=document_id, dry_run=False)
            commit_relationships(db, project_id, document_id)
            db.commit()
        _update(job_id, progress=90, stage="COMPARING")
        with SessionLocal() as db:
            compare_pdf_to_kmz(db, project_id, document_id)
            document = db.scalar(select(Document).where(
                Document.id == document_id, Document.project_id == project_id,
            ))
            if document:
                document.processing_status = "PARSED"
            job = db.get(PdfProcessingJob, job_id)
            if job is None:
                return
            if job.cancel_requested:
                raise JobCancelled()
            job.status, job.stage, job.progress = "SUCCEEDED", "COMPLETE", 100
            job.heartbeat_at = job.finished_at = datetime.now(timezone.utc)
            job.error_code = job.error_message = None
            db.commit()
    except JobCancelled:
        with SessionLocal() as db:
            job = db.get(PdfProcessingJob, job_id)
            if job:
                job.status, job.stage = "CANCELLED", "CANCELLED"
                job.finished_at = datetime.now(timezone.utc)
                db.commit()
        return
    except Exception as exc:
        with SessionLocal() as db:
            job = db.get(PdfProcessingJob, job_id)
            if job:
                job.status, job.stage = "FAILED", "FAILED"
                job.error_code = "PDF_PROCESSING_FAILED"
                job.error_message = "PDF processing failed. Retry the job or contact an administrator."
                job.finished_at = datetime.now(timezone.utc)
                document = db.get(Document, job.document_id)
                if document:
                    document.processing_status = "ERROR"
                db.commit()
        raise RuntimeError(f"PDF job {job_id} failed") from None
