import io
import json
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.pole_entities import manual_match, unmatch
from app.db.base import Base
from app.db.deps import get_db
from app.main import app
from app.models.asset import Asset
from app.models.conflict import Conflict
from app.models.document import Document
from app.models.pdf_extraction import PdfPoleEvidence
from app.models.pole_entity import PoleEntity, PoleEntityAudit, PoleEntitySource, PoleRelationship
from app.models.project import Project
from app.schemas.pole_entity import ManualMatchRequest, UnmatchRequest
from app.services.pdf_conflict_engine import compare_pdf_to_kmz
from app.services.pole_entity_resolution import commit_relationships, resolve_pole_entities


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        yield session
    engine.dispose()


def _project_document(db: Session) -> tuple[Project, Document]:
    project = Project(project_code=f"TEST-{uuid.uuid4()}", name="PDF Entity Test", status="ACTIVE")
    db.add(project)
    db.flush()
    document = Document(
        project_id=project.id,
        filename="permit.pdf",
        document_type="PDF",
        sha256=uuid.uuid4().hex + uuid.uuid4().hex,
        mime_type="application/pdf",
        size_bytes=100,
        processing_status="PARSED",
    )
    db.add(document)
    db.flush()
    return project, document


def _evidence(
    db: Session,
    document: Document,
    *,
    pole_id: str | None = None,
    from_id: str | None = None,
    to_id: str | None = None,
    length: float | None = None,
) -> PdfPoleEvidence:
    item = PdfPoleEvidence(
        document_id=document.id,
        page_number=1,
        evidence_type="SPAN" if from_id else "POLE_ID",
        pole_id=pole_id,
        from_pole_id=from_id,
        to_pole_id=to_id,
        span_length_ft=length,
        raw_text=f"POLE #{pole_id}" if pole_id else f"POLE #{from_id} TO POLE #{to_id} ({length}')",
        bbox_json="[1, 2, 3, 4]",
        confidence=0.98,
    )
    db.add(item)
    db.flush()
    return item


def _asset(db: Session, project: Project, pole_id: str, *, lon=-121.0, lat=39.0) -> Asset:
    asset = Asset(
        project_id=project.id,
        asset_type="POLE",
        name=f"Pole #{pole_id}",
        status="VERIFIED",
        longitude=lon,
        latitude=lat,
        geometry_type="Point",
    )
    db.add(asset)
    db.flush()
    return asset


def test_exact_pole_id_resolution(db):
    project, document = _project_document(db)
    _evidence(db, document, pole_id="123456789")
    asset = _asset(db, project, "123456789")

    report = resolve_pole_entities(db, project.id, document_id=document.id)
    db.commit()

    entity = db.scalar(select(PoleEntity).where(PoleEntity.project_id == project.id))
    assert report["resolved"] == 1
    assert entity.resolution_status == "RESOLVED"
    assert (entity.longitude, entity.latitude) == (asset.longitude, asset.latitude)
    assert db.scalar(select(func.count()).select_from(PoleEntitySource)) == 2


def test_ambiguous_and_unmatched_resolution(db):
    project, document = _project_document(db)
    _evidence(db, document, pole_id="123456789")
    _evidence(db, document, pole_id="987654321")
    _asset(db, project, "123456789", lon=-121.0)
    _asset(db, project, "123456789", lon=-122.0)

    report = resolve_pole_entities(db, project.id, document_id=document.id)
    db.commit()

    statuses = {
        entity.canonical_pole_id: entity.resolution_status
        for entity in db.scalars(select(PoleEntity).where(PoleEntity.project_id == project.id))
    }
    assert report["ambiguous"] == 1
    assert report["unresolved"] == 1
    assert statuses == {"123456789": "AMBIGUOUS", "987654321": "UNRESOLVED"}


def test_resolution_rerun_is_idempotent(db):
    project, document = _project_document(db)
    _evidence(db, document, pole_id="123456789")
    _asset(db, project, "123456789")

    first = resolve_pole_entities(db, project.id, document_id=document.id)
    db.commit()
    counts_before = (
        db.scalar(select(func.count()).select_from(PoleEntity)),
        db.scalar(select(func.count()).select_from(PoleEntitySource)),
    )
    second = resolve_pole_entities(db, project.id, document_id=document.id)
    db.commit()

    assert first["created_entities"] == 1
    assert second["reused_entities"] == 1
    assert counts_before == (
        db.scalar(select(func.count()).select_from(PoleEntity)),
        db.scalar(select(func.count()).select_from(PoleEntitySource)),
    )


def test_manual_match_and_unmatch_are_audited(db):
    project, document = _project_document(db)
    _evidence(db, document, pole_id="987654321")
    asset = _asset(db, project, "123456789")
    resolve_pole_entities(db, project.id, document_id=document.id)
    db.commit()
    entity = db.scalar(select(PoleEntity).where(PoleEntity.canonical_pole_id == "987654321"))

    matched = manual_match(
        entity.id,
        ManualMatchRequest(asset_id=asset.id, reason="Field verified", reviewer="engineer@example.com"),
        db,
    )
    assert matched.resolution_status == "MANUAL"
    assert matched.longitude == asset.longitude

    resolve_pole_entities(db, project.id, document_id=document.id)
    db.commit()
    db.refresh(entity)
    assert entity.resolution_status == "MANUAL"
    assert db.scalar(select(func.count()).select_from(PoleEntitySource).where(
        PoleEntitySource.pole_entity_id == entity.id,
        PoleEntitySource.source_type == "ASSET",
        PoleEntitySource.match_method == "MANUAL",
    )) == 1

    unmatched = unmatch(
        entity.id,
        UnmatchRequest(reason="Wrong source pole", reviewer="engineer@example.com"),
        db,
    )
    assert unmatched.resolution_status == "UNRESOLVED"
    assert unmatched.longitude is None
    assert db.scalar(select(func.count()).select_from(PoleEntitySource).where(
        PoleEntitySource.source_type == "ASSET"
    )) == 0
    assert set(db.scalars(
        select(PoleEntityAudit.action)
        .where(PoleEntityAudit.pole_entity_id == entity.id)
    )) == {"MANUAL_MATCH", "UNMATCH"}


@pytest.mark.parametrize(
    ("matched_ids", "expected_status"),
    [({"123456789", "987654321"}, "RESOLVED"), ({"123456789"}, "PARTIAL"), (set(), "UNRESOLVED")],
)
def test_span_resolution_and_duplicate_prevention(db, matched_ids, expected_status):
    project, document = _project_document(db)
    _evidence(db, document, from_id="123456789", to_id="987654321", length=100)
    for index, pole_id in enumerate(matched_ids):
        _asset(db, project, pole_id, lon=-121.0 + index * 0.0001)
    resolve_pole_entities(db, project.id, document_id=document.id)
    first = commit_relationships(db, project.id, document.id)
    second = commit_relationships(db, project.id, document.id)
    db.commit()

    relationship = db.scalar(select(PoleRelationship).where(PoleRelationship.project_id == project.id))
    assert relationship.resolution_status == expected_status
    assert first["created"] == 1
    assert second["reused"] == 1
    assert db.scalar(select(func.count()).select_from(PoleRelationship)) == 1


def test_calculated_distance_mismatch_conflict(db):
    project, document = _project_document(db)
    _evidence(db, document, from_id="123456789", to_id="987654321", length=500)
    _asset(db, project, "123456789", lon=-121.0, lat=39.0)
    _asset(db, project, "987654321", lon=-120.9999, lat=39.0)
    resolve_pole_entities(db, project.id, document_id=document.id)
    commit_relationships(db, project.id, document.id)
    db.commit()

    conflicts = compare_pdf_to_kmz(db, project.id, document.id)

    assert any(item.conflict_type == "PDF_SPAN_LENGTH_MISMATCH" for item in conflicts)


def _minimal_pdf(text: str) -> bytes:
    escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream = f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, 1):
        offsets.append(len(output))
        output.extend(f"{index} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode())
    output.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return bytes(output)


def test_pdf_dry_run_commit_resolution_review_and_conflict_integration(db):
    project, _ = _project_document(db)
    _asset(db, project, "123456789", lon=-121.0, lat=39.0)
    _asset(db, project, "987654321", lon=-120.9999, lat=39.0)
    db.commit()

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    try:
        client = TestClient(app)
        response = client.post(
            "/api/v1/pdf-pole-extractions/dry-run",
            data={"project_id": str(project.id)},
            files={
                "file": (
                    "permit.pdf",
                    _minimal_pdf("FROM POLE #123456789 TO POLE #987654321 (500') POLE #555555555"),
                    "application/pdf",
                )
            },
        )
        assert response.status_code == 200, response.text
        document_id = response.json()["document"]["id"]
        assets_before = db.scalar(select(func.count()).select_from(Asset))

        committed = client.post(
            f"/api/v1/pdf-pole-extractions/{document_id}/commit",
            json={"confirmed": True, "reason": "Integration test", "reviewer": "pytest"},
        )
        assert committed.status_code == 200, committed.text
        assert committed.json()["assets_created"] == 0
        assert db.scalar(select(func.count()).select_from(Asset)) == assets_before

        repeated_dry_run = client.post(
            "/api/v1/pdf-pole-extractions/dry-run",
            data={"project_id": str(project.id)},
            files={
                "file": (
                    "../../permit.pdf",
                    _minimal_pdf("FROM POLE #123456789 TO POLE #987654321 (500') POLE #555555555"),
                    "application/pdf",
                )
            },
        )
        assert repeated_dry_run.status_code == 200, repeated_dry_run.text
        assert repeated_dry_run.json()["document"]["duplicate"] is True
        assert repeated_dry_run.json()["document"]["filename"] == "permit.pdf"
        current_evidence_ids = set(db.scalars(select(PdfPoleEvidence.id).where(
            PdfPoleEvidence.document_id == uuid.UUID(document_id)
        )))
        pdf_source_ids = set(db.scalars(select(PoleEntitySource.source_id).where(
            PoleEntitySource.source_type == "PDF_EVIDENCE"
        )))
        assert pdf_source_ids <= current_evidence_ids

        recommitted = client.post(
            f"/api/v1/pdf-pole-extractions/{document_id}/commit",
            json={"confirmed": True, "reason": "Idempotency test", "reviewer": "pytest"},
        )
        assert recommitted.status_code == 200, recommitted.text
        assert recommitted.json()["relationships"]["created"] == 1
        second_commit = client.post(
            f"/api/v1/pdf-pole-extractions/{document_id}/commit",
            json={"confirmed": True, "reason": "Idempotency test", "reviewer": "pytest"},
        )
        assert second_commit.status_code == 200, second_commit.text
        assert second_commit.json()["relationships"]["created"] == 0
        assert second_commit.json()["relationships"]["reused"] == 1

        entities = client.get("/api/v1/pole-entities", params={"project_id": str(project.id)})
        relationships = client.get("/api/v1/pole-relationships", params={"project_id": str(project.id)})
        review = client.get("/api/v1/review/pdf-items", params={"project_id": str(project.id)})
        compared = client.post(f"/api/v1/pdf-pole-extractions/{document_id}/compare")
        assert entities.status_code == relationships.status_code == review.status_code == compared.status_code == 200
        assert entities.json()["total"] == 3
        assert relationships.json()["total"] == 1
        assert review.json()["total"] >= 1
        assert any(item["conflict_type"] == "PDF_SPAN_LENGTH_MISMATCH" for item in compared.json()["conflicts"])
    finally:
        app.dependency_overrides.clear()


def test_pdf_upload_rejects_non_pdf_content(db):
    project, _ = _project_document(db)
    db.commit()

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    try:
        response = TestClient(app).post(
            "/api/v1/pdf-pole-extractions/dry-run",
            data={"project_id": str(project.id)},
            files={"file": ("fake.pdf", b"not a pdf", "application/pdf")},
        )
        assert response.status_code == 422
    finally:
        app.dependency_overrides.clear()
