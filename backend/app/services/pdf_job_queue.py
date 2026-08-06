from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from redis import Redis
from sqlalchemy import select

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.pdf_extraction import PdfProcessingJob


QUEUE_KEY = "telecomos:pdf-jobs"
WORKER_HEARTBEAT_KEY = "telecomos:pdf-worker:heartbeat"


def redis_client() -> Redis:
    return Redis.from_url(settings.redis_url, decode_responses=True)


def enqueue(job_id: uuid.UUID, *, client: Redis | None = None) -> None:
    (client or redis_client()).lpush(QUEUE_KEY, str(job_id))


def request_cancel(job: PdfProcessingJob) -> None:
    job.cancel_requested = True
    if job.status == "QUEUED":
        job.status = "CANCELLED"
        job.stage = "CANCELLED"
        job.finished_at = datetime.now(timezone.utc)


def recover_stale_jobs() -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=settings.pdf_job_stale_seconds)
    recovered: list[uuid.UUID] = []
    with SessionLocal() as db:
        jobs = list(db.scalars(select(PdfProcessingJob).where(
            PdfProcessingJob.status == "RUNNING",
            PdfProcessingJob.heartbeat_at < cutoff,
        ).with_for_update(skip_locked=True)))
        for job in jobs:
            if job.cancel_requested:
                job.status, job.stage = "CANCELLED", "CANCELLED"
                job.finished_at = datetime.now(timezone.utc)
            elif job.attempts < job.max_attempts:
                job.status, job.stage = "QUEUED", "RECOVERED"
                recovered.append(job.id)
            else:
                job.status, job.stage = "FAILED", "FAILED"
                job.error_code = "WORKER_STALE"
                job.error_message = "Worker stopped before processing completed."
                job.finished_at = datetime.now(timezone.utc)
        db.commit()
    for job_id in recovered:
        enqueue(job_id)
    return len(recovered)
