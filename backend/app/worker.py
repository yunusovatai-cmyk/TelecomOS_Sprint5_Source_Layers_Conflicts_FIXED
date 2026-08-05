from __future__ import annotations

import logging
import time
import uuid

from app.core.config import settings
from app.services.pdf_job_processor import process_job
from app.services.pdf_job_queue import QUEUE_KEY, WORKER_HEARTBEAT_KEY, enqueue, recover_stale_jobs, redis_client
from app.db.session import SessionLocal
from app.models.pdf_extraction import PdfProcessingJob
from app.models.project import Project  # noqa: F401 -- register FK target in worker metadata


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("pdf-worker")


def run() -> None:
    client = redis_client()
    recover_stale_jobs()
    logger.info("PDF worker started")
    while True:
        client.set(WORKER_HEARTBEAT_KEY, str(time.time()), ex=max(10, settings.pdf_worker_poll_seconds * 5))
        item = client.brpop(QUEUE_KEY, timeout=settings.pdf_worker_poll_seconds)
        if item is None:
            recover_stale_jobs()
            continue
        try:
            process_job(uuid.UUID(item[1]))
        except Exception:
            logger.error("PDF job failed job_id=%s", item[1])
            with SessionLocal() as db:
                job = db.get(PdfProcessingJob, uuid.UUID(item[1]))
                if job and job.status == "FAILED" and job.attempts < job.max_attempts and not job.cancel_requested:
                    job.status, job.stage = "QUEUED", "RETRY_QUEUED"
                    db.commit()
                    enqueue(job.id, client=client)
                elif job and job.status == "QUEUED" and not job.cancel_requested:
                    enqueue(job.id, client=client)


if __name__ == "__main__":
    run()
