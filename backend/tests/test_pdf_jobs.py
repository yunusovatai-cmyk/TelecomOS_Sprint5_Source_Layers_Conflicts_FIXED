import hashlib
import io
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.deps import get_db
from app.main import app
from app.models.document import Document
from app.models.pdf_extraction import DocumentBlob, PdfProcessingJob
from app.models.project import Project
from app.services.object_storage import StoredObject, cleanup_orphan_objects, document_object_key, put_pdf


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        yield session
    engine.dispose()


@pytest.fixture()
def client(db, monkeypatch):
    def override_db():
        yield db
    monkeypatch.setattr(
        "app.api.pdf_jobs.put_pdf",
        lambda **kwargs: StoredObject("private", f"projects/{kwargs['project_id'].hex}/documents/{kwargs['document_id'].hex}/{kwargs['expected_sha256']}.pdf", kwargs["expected_sha256"], len(kwargs["content"]), "application/pdf"),
    )
    monkeypatch.setattr("app.api.pdf_jobs.enqueue", lambda job_id: None)
    app.dependency_overrides[get_db] = override_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def _project(db):
    project = Project(project_code=f"JOB-{uuid.uuid4()}", name="Job test", status="ACTIVE")
    db.add(project); db.commit(); return project


def test_pdf_job_upload_is_idempotent_by_project_and_sha(db, client, monkeypatch):
    project = _project(db)
    pdf = b"%PDF-1.4\nsmall fixture"
    uploads = []
    def store(**kwargs):
        uploads.append(kwargs["expected_sha256"])
        return StoredObject("private", f"projects/{kwargs['project_id'].hex}/documents/{kwargs['document_id'].hex}/{kwargs['expected_sha256']}.pdf", kwargs["expected_sha256"], len(kwargs["content"]), "application/pdf")
    monkeypatch.setattr("app.api.pdf_jobs.put_pdf", store)
    first = client.post("/api/v1/pdf-jobs", data={"project_id": str(project.id)}, files={"file": ("a.pdf", pdf, "application/pdf")})
    second = client.post("/api/v1/pdf-jobs", data={"project_id": str(project.id)}, files={"file": ("../../b.pdf", pdf, "application/pdf")})
    assert first.status_code == second.status_code == 202
    assert first.json()["id"] == second.json()["id"]
    assert second.json()["duplicate_document"] is True
    assert second.json()["reused_job"] is True
    documents = db.query(Document).filter_by(project_id=project.id).all()
    assert len(documents) == 1 and documents[0].storage_object_key.startswith(f"projects/{project.id.hex}/")
    assert db.query(DocumentBlob).count() == 0
    assert uploads == [hashlib.sha256(pdf).hexdigest()]


def test_job_project_scoping_cancel_retry_and_uuid_validation(db, client, monkeypatch):
    project, other = _project(db), _project(db)
    document = Document(project_id=project.id, filename="a.pdf", document_type="PDF", sha256="a" * 64, mime_type="application/pdf", size_bytes=10, processing_status="REGISTERED")
    db.add(document); db.flush()
    job = PdfProcessingJob(project_id=project.id, document_id=document.id, idempotency_key=f"{project.id}:a:FULL_PIPELINE")
    db.add(job); db.commit()
    assert client.get(f"/api/v1/pdf-jobs/{job.id}", params={"project_id": str(other.id)}).status_code == 404
    assert client.get(f"/api/v1/documents/{document.id}/page/1.png", params={"project_id": str(other.id)}).status_code == 404
    listed = client.get("/api/v1/documents", params={"project_id": str(other.id)})
    assert listed.status_code == 200 and all(item["id"] != str(document.id) for item in listed.json())
    assert client.get(f"/api/v1/pdf-jobs/{job.id}", params={"project_id": "bad"}).status_code == 422
    cancelled = client.post(f"/api/v1/pdf-jobs/{job.id}/cancel", params={"project_id": str(project.id)})
    assert cancelled.json()["status"] == "CANCELLED"
    retried = client.post(f"/api/v1/pdf-jobs/{job.id}/retry", params={"project_id": str(project.id)})
    assert retried.status_code == 202 and retried.json()["status"] == "QUEUED"


def test_storage_failure_returns_safe_api_error(db, client, monkeypatch):
    project = _project(db)
    monkeypatch.setattr(
        "app.api.pdf_jobs.put_pdf",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("secret internal PDF parser content")),
    )
    response = client.post(
        "/api/v1/pdf-jobs", data={"project_id": str(project.id)},
        files={"file": ("permit.pdf", b"%PDF-1.4\nfixture", "application/pdf")},
    )
    assert response.status_code == 503
    assert response.json() == {"detail": "PDF object storage is unavailable."}
    assert "secret" not in response.text


class FakeResponse(io.BytesIO):
    def release_conn(self): pass


class FakeMinio:
    def __init__(self): self.objects = {}; self.policy_deleted = False
    def bucket_exists(self, bucket): return True
    def delete_bucket_policy(self, bucket): self.policy_deleted = True
    def put_object(self, bucket, key, stream, length, **kwargs): self.objects[(bucket, key)] = stream.read(length)
    def get_object(self, bucket, key): return FakeResponse(self.objects[(bucket, key)])


class FakeListedObject:
    def __init__(self, name, modified): self.object_name, self.last_modified = name, modified


class FakeCleanupMinio(FakeMinio):
    def __init__(self, listed): super().__init__(); self.listed, self.removed = listed, []
    def list_objects(self, bucket, prefix, recursive): return self.listed
    def remove_object(self, bucket, key): self.removed.append((bucket, key))


def test_minio_pdf_upload_download_signature_sha_and_safe_key():
    client = FakeMinio(); content = b"%PDF-1.4\nfixture"; digest = hashlib.sha256(content).hexdigest()
    stored = put_pdf(project_id=uuid.uuid4(), document_id=uuid.uuid4(), content=content, expected_sha256=digest, client=client)
    assert client.objects[(stored.bucket, stored.object_key)] == content
    assert client.policy_deleted and ".." not in stored.object_key
    with pytest.raises(ValueError):
        put_pdf(project_id=uuid.uuid4(), document_id=uuid.uuid4(), content=b"not-pdf", client=client)


def test_orphan_cleanup_is_dry_run_by_default_and_honors_references_and_grace_period():
    old = datetime.now(timezone.utc) - timedelta(hours=2)
    recent = datetime.now(timezone.utc) - timedelta(minutes=5)
    referenced_key = "projects/a/documents/b/reference.pdf"
    orphan_key = "projects/a/documents/b/orphan.pdf"
    recent_key = "projects/a/documents/b/recent.pdf"
    client = FakeCleanupMinio([
        FakeListedObject(referenced_key, old), FakeListedObject(orphan_key, old), FakeListedObject(recent_key, recent),
    ])
    referenced = {("telecomos-private-documents", referenced_key)}
    assert cleanup_orphan_objects(referenced, client=client) == [orphan_key]
    assert client.removed == []
    assert cleanup_orphan_objects(referenced, client=client, apply=True) == [orphan_key]
    assert client.removed == [("telecomos-private-documents", orphan_key)]


def test_stale_running_job_recovery_and_retry_ceiling(monkeypatch):
    from app.services import pdf_job_queue
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as db:
        project = Project(project_code=f"STALE-{uuid.uuid4()}", name="Stale", status="ACTIVE")
        db.add(project); db.flush()
        document = Document(project_id=project.id, filename="a.pdf", document_type="PDF", sha256="b" * 64, mime_type="application/pdf", size_bytes=10, processing_status="REGISTERED")
        db.add(document); db.flush()
        recoverable = PdfProcessingJob(
            project_id=project.id, document_id=document.id, idempotency_key="recoverable",
            status="RUNNING", attempts=1, max_attempts=3,
            heartbeat_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )
        exhausted = PdfProcessingJob(
            project_id=project.id, document_id=document.id, idempotency_key="exhausted",
            status="RUNNING", attempts=3, max_attempts=3,
            heartbeat_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )
        db.add_all([recoverable, exhausted]); db.commit()
        recoverable_id, exhausted_id = recoverable.id, exhausted.id
    queued = []
    monkeypatch.setattr(pdf_job_queue, "SessionLocal", factory)
    monkeypatch.setattr(pdf_job_queue, "enqueue", lambda job_id: queued.append(job_id))
    assert pdf_job_queue.recover_stale_jobs() == 1
    with factory() as db:
        assert db.get(PdfProcessingJob, recoverable_id).status == "QUEUED"
        assert db.get(PdfProcessingJob, exhausted_id).status == "FAILED"
        assert db.get(PdfProcessingJob, exhausted_id).error_code == "WORKER_STALE"
    assert queued == [recoverable_id]
    engine.dispose()


def test_worker_records_safe_failure_and_honors_prestart_cancel(monkeypatch):
    from app.services import pdf_job_processor
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as db:
        project = Project(project_code=f"FAIL-{uuid.uuid4()}", name="Failure", status="ACTIVE")
        db.add(project); db.flush()
        document = Document(
            project_id=project.id, filename="a.pdf", document_type="PDF", sha256="c" * 64,
            mime_type="application/pdf", size_bytes=10, processing_status="REGISTERED",
            storage_bucket="private", storage_object_key="projects/a/documents/b/c.pdf", storage_size_bytes=10,
        )
        db.add(document); db.flush()
        failed = PdfProcessingJob(project_id=project.id, document_id=document.id, idempotency_key="failed")
        cancelled = PdfProcessingJob(project_id=project.id, document_id=document.id, idempotency_key="cancelled", cancel_requested=True)
        db.add_all([failed, cancelled]); db.commit()
        failed_id, cancelled_id = failed.id, cancelled.id
    monkeypatch.setattr(pdf_job_processor, "SessionLocal", factory)
    monkeypatch.setattr(pdf_job_processor, "_load_content", lambda document: (_ for _ in ()).throw(ValueError("sensitive parser detail")))
    with pytest.raises(RuntimeError, match="PDF job .* failed") as caught:
        pdf_job_processor.process_job(failed_id)
    assert "sensitive parser detail" not in str(caught.value)
    pdf_job_processor.process_job(cancelled_id)
    with factory() as db:
        failed_job = db.get(PdfProcessingJob, failed_id)
        assert failed_job.status == "FAILED"
        assert failed_job.error_code == "PDF_PROCESSING_FAILED"
        assert "sensitive" not in failed_job.error_message
        assert db.get(PdfProcessingJob, cancelled_id).status == "CANCELLED"
    engine.dispose()
