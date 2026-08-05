from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.pdf_pole_extractions import _read_pdf_upload, _safe_filename
from app.core.config import settings
from app.db.deps import get_db
from app.models.document import Document
from app.models.pdf_extraction import PdfProcessingJob
from app.models.project import Project
from app.schemas.pdf_extraction import PdfJobListResponse, PdfJobResponse
from app.services.document_classifier import extract_revision
from app.services.object_storage import put_pdf, remove_object
from app.services.pdf_job_queue import enqueue, request_cancel


router = APIRouter(prefix="/pdf-jobs", tags=["pdf-jobs"])


def serialize_job(job: PdfProcessingJob, *, duplicate: bool = False, reused: bool = False) -> dict:
    def iso(value):
        return value.isoformat() if value else None
    return {
        "id": str(job.id), "project_id": str(job.project_id), "document_id": str(job.document_id),
        "operation": job.operation, "status": job.status, "progress": job.progress, "stage": job.stage,
        "attempts": job.attempts, "max_attempts": job.max_attempts, "error_code": job.error_code,
        "error_message": job.error_message, "queued_at": iso(job.queued_at), "started_at": iso(job.started_at),
        "heartbeat_at": iso(job.heartbeat_at), "finished_at": iso(job.finished_at),
        "created_at": iso(job.created_at), "updated_at": iso(job.updated_at),
        "duplicate_document": duplicate, "reused_job": reused,
    }


def _scoped_job(db: Session, job_id: uuid.UUID, project_id: uuid.UUID | None) -> PdfProcessingJob:
    statement = select(PdfProcessingJob).where(PdfProcessingJob.id == job_id)
    if project_id is not None:
        statement = statement.where(PdfProcessingJob.project_id == project_id)
    job = db.scalar(statement)
    if job is None:
        raise HTTPException(status_code=404, detail="PDF job not found.")
    return job


def create_job_record(db: Session, document: Document) -> tuple[PdfProcessingJob, bool]:
    idempotency_key = f"{document.project_id}:{document.sha256}:FULL_PIPELINE"
    job = db.scalar(select(PdfProcessingJob).where(PdfProcessingJob.idempotency_key == idempotency_key))
    if job is not None:
        return job, True
    job = PdfProcessingJob(
        project_id=document.project_id, document_id=document.id, operation="FULL_PIPELINE",
        idempotency_key=idempotency_key, max_attempts=settings.pdf_job_max_attempts,
    )
    db.add(job)
    return job, False


@router.post("", response_model=PdfJobResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_pdf_job(
    project_id: uuid.UUID = Form(...), file: UploadFile = File(...), db: Session = Depends(get_db),
) -> dict:
    filename = _safe_filename(file.filename)
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")
    content = await _read_pdf_upload(file)
    digest = hashlib.sha256(content).hexdigest()
    project = db.scalar(select(Project).where(Project.id == project_id).with_for_update())
    if project is None:
        db.rollback()
        raise HTTPException(status_code=404, detail="Project not found.")
    document = db.scalar(select(Document).where(Document.project_id == project_id, Document.sha256 == digest))
    duplicate = document is not None
    if document is None:
        document = Document(
            project_id=project_id, filename=filename, document_type="PDF", revision=extract_revision(filename),
            sha256=digest, mime_type="application/pdf", size_bytes=len(content), processing_status="REGISTERED",
        )
        db.add(document)
        db.flush()

    uploaded = None
    if not document.storage_object_key:
        try:
            uploaded = put_pdf(
                project_id=project_id, document_id=document.id, content=content, expected_sha256=digest,
            )
            document.storage_bucket = uploaded.bucket
            document.storage_object_key = uploaded.object_key
            document.storage_size_bytes = uploaded.size_bytes
            document.storage_mime_type = uploaded.mime_type
        except Exception as exc:
            db.rollback()
            raise HTTPException(status_code=503, detail="PDF object storage is unavailable.") from exc

    idempotency_key = f"{project_id}:{digest}:FULL_PIPELINE"
    job, reused = create_job_record(db, document)
    try:
        db.commit()
        db.refresh(job)
    except IntegrityError:
        db.rollback()
        if uploaded is not None and not duplicate:
            remove_object(uploaded.bucket, uploaded.object_key)
        job = db.scalar(select(PdfProcessingJob).where(PdfProcessingJob.idempotency_key == idempotency_key))
        if job is None:
            raise
        reused = True
    except Exception:
        db.rollback()
        if uploaded is not None and not duplicate:
            remove_object(uploaded.bucket, uploaded.object_key)
        raise
    if job.status == "QUEUED" and not reused:
        try:
            enqueue(job.id)
        except Exception as exc:
            job.status, job.stage = "FAILED", "QUEUE_FAILED"
            job.error_code = "QUEUE_UNAVAILABLE"
            job.error_message = "The PDF queue is temporarily unavailable. Retry the job."
            db.commit()
            raise HTTPException(status_code=503, detail=job.error_message) from exc
    return serialize_job(job, duplicate=duplicate, reused=reused)


@router.get("/{job_id}", response_model=PdfJobResponse)
def get_pdf_job(
    job_id: uuid.UUID, project_id: uuid.UUID = Query(...), db: Session = Depends(get_db),
) -> dict:
    return serialize_job(_scoped_job(db, job_id, project_id))


@router.get("", response_model=PdfJobListResponse)
def list_pdf_jobs(
    project_id: uuid.UUID, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> dict:
    base = select(PdfProcessingJob).where(PdfProcessingJob.project_id == project_id)
    total = db.scalar(select(func.count()).select_from(PdfProcessingJob).where(
        PdfProcessingJob.project_id == project_id
    )) or 0
    jobs = list(db.scalars(base.order_by(PdfProcessingJob.created_at.desc()).offset(offset).limit(limit)))
    return {"items": [serialize_job(job) for job in jobs], "total": total, "offset": offset, "limit": limit}


@router.post("/{job_id}/cancel", response_model=PdfJobResponse)
def cancel_pdf_job(
    job_id: uuid.UUID, project_id: uuid.UUID = Query(...), db: Session = Depends(get_db),
) -> dict:
    job = _scoped_job(db, job_id, project_id)
    if job.status in {"SUCCEEDED", "FAILED", "CANCELLED"}:
        raise HTTPException(status_code=409, detail="Only queued or running jobs can be cancelled.")
    request_cancel(job)
    db.commit()
    db.refresh(job)
    return serialize_job(job)


@router.post("/{job_id}/retry", response_model=PdfJobResponse, status_code=status.HTTP_202_ACCEPTED)
def retry_pdf_job(
    job_id: uuid.UUID, project_id: uuid.UUID = Query(...), db: Session = Depends(get_db),
) -> dict:
    job = _scoped_job(db, job_id, project_id)
    if job.status not in {"FAILED", "CANCELLED"}:
        raise HTTPException(status_code=409, detail="Only failed or cancelled jobs can be retried.")
    if job.attempts >= job.max_attempts:
        raise HTTPException(status_code=409, detail="Maximum retry attempts reached.")
    job.status, job.stage, job.progress = "QUEUED", "QUEUED", 0
    job.cancel_requested = False
    job.error_code = job.error_message = None
    job.queued_at = datetime.now(timezone.utc)
    job.finished_at = None
    db.commit()
    try:
        enqueue(job.id)
    except Exception as exc:
        job.status, job.stage = "FAILED", "QUEUE_FAILED"
        job.error_code = "QUEUE_UNAVAILABLE"
        job.error_message = "The PDF queue is temporarily unavailable. Retry the job."
        db.commit()
        raise HTTPException(status_code=503, detail=job.error_message) from exc
    db.refresh(job)
    return serialize_job(job)
