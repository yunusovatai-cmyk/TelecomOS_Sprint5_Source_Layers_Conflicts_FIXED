from __future__ import annotations

import asyncio
import hashlib
import json
import re
import uuid
from io import BytesIO
from pathlib import PurePosixPath

import pypdfium2 as pdfium
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.db.deps import get_db
from app.models.asset import Asset
from app.models.document import Document
from app.core.config import settings
from app.models.pdf_extraction import DocumentBlob, PdfPageText, PdfPoleEvidence
from app.models.project import Project
from app.models.pole_entity import PoleEntity, PoleEntitySource, PoleRelationship
from app.schemas.pdf_extraction import EvidenceReviewRequest, PdfPoleDryRunResponse, PdfWorkspaceResponse
from app.schemas.pole_entity import (
    CommitReport,
    CommitRequest,
    DocumentResolutionRequest,
    ResolutionReport,
)
from app.services.document_classifier import extract_revision
from app.services.pdf_pole_extractor import extract_evidence, extract_native_pages
from app.services.pdf_conflict_engine import compare_pdf_to_kmz
from app.services.pole_entity_resolution import commit_relationships, resolve_pole_entities

router = APIRouter(prefix="/pdf-pole-extractions", tags=["pdf-pole-extractions"])

MAX_PDF_SIZE = 50 * 1024 * 1024
UPLOAD_CHUNK_SIZE = 1024 * 1024
ASSET_POLE_ID_RE = re.compile(r"\b(\d{9})\b")


def _asset_pole_ids(asset: Asset) -> set[str]:
    return set(ASSET_POLE_ID_RE.findall(asset.name or ""))


def _safe_filename(filename: str | None) -> str:
    basename = PurePosixPath((filename or "permit-plan.pdf").replace("\\", "/")).name
    sanitized = "".join(character for character in basename if character.isprintable() and character not in "\x00\r\n")
    return sanitized[:255] or "permit-plan.pdf"


async def _read_pdf_upload(file: UploadFile) -> bytes:
    chunks: list[bytes] = []
    size = 0
    while chunk := await file.read(UPLOAD_CHUNK_SIZE):
        size += len(chunk)
        if size > MAX_PDF_SIZE:
            raise HTTPException(status_code=413, detail=f"PDF must not exceed {MAX_PDF_SIZE} bytes.")
        chunks.append(chunk)
    content = b"".join(chunks)
    if not content:
        raise HTTPException(status_code=400, detail="PDF must not be empty.")
    if not content.startswith(b"%PDF-"):
        raise HTTPException(status_code=422, detail="Uploaded content is not a PDF file.")
    return content


@router.post("/dry-run", response_model=PdfPoleDryRunResponse)
async def dry_run_pdf_pole_extraction(
    project_id: uuid.UUID = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
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
    document = db.scalar(
        select(Document).where(Document.project_id == project_id, Document.sha256 == digest)
    )
    duplicate = document is not None
    if document is None:
        document = Document(
            project_id=project_id,
            filename=filename,
            document_type="PDF",
            revision=extract_revision(filename),
            sha256=digest,
            mime_type=file.content_type or "application/pdf",
            size_bytes=len(content),
            processing_status="REGISTERED",
        )
        db.add(document)
        db.flush()
    document_id = document.id
    db.commit()

    try:
        pages = await asyncio.wait_for(
            run_in_threadpool(
                extract_native_pages,
                content,
                max_pages=settings.pdf_max_pages,
                max_words=settings.pdf_max_words,
            ),
            timeout=settings.pdf_extraction_timeout_seconds,
        )
        evidence = extract_evidence(pages, max_evidence=settings.pdf_max_evidence)
    except Exception as exc:
        document = db.get(Document, document_id)
        if document is None:
            raise HTTPException(status_code=404, detail="PDF document not found after registration.") from exc
        document.processing_status = "ERROR"
        db.commit()
        raise HTTPException(status_code=422, detail="Unable to extract native PDF text.") from exc

    # Keep the project lock only while replacing derived rows. Native PDF
    # parsing happens above without an open database transaction.
    project = db.scalar(select(Project).where(Project.id == project_id).with_for_update())
    document = db.scalar(select(Document).where(
        Document.id == document_id,
        Document.project_id == project_id,
    ))
    if project is None or document is None:
        db.rollback()
        raise HTTPException(status_code=404, detail="PDF document project no longer exists.")
    evidence_ids = list(db.scalars(select(PdfPoleEvidence.id).where(PdfPoleEvidence.document_id == document.id)))
    if evidence_ids:
        db.execute(delete(PoleRelationship).where(PoleRelationship.source_evidence_id.in_(evidence_ids)))
        db.execute(delete(PoleEntitySource).where(
            PoleEntitySource.source_type == "PDF_EVIDENCE",
            PoleEntitySource.source_id.in_(evidence_ids),
        ))
    db.execute(delete(PdfPoleEvidence).where(PdfPoleEvidence.document_id == document.id))
    db.execute(delete(PdfPageText).where(PdfPageText.document_id == document.id))

    blob = db.scalar(select(DocumentBlob).where(DocumentBlob.document_id == document.id))
    if blob is None:
        db.add(DocumentBlob(document_id=document.id, content=content))
    elif blob.content != content:
        blob.content = content

    assets = list(db.scalars(select(Asset).where(Asset.project_id == project_id)))
    assets_by_pole_id: dict[str, Asset] = {}
    for asset in assets:
        for pole_id in _asset_pole_ids(asset):
            assets_by_pole_id.setdefault(pole_id, asset)

    for page in pages:
        db.add(PdfPageText(
            document_id=document.id,
            page_number=page.page_number,
            raw_text=page.raw_text,
            page_width=page.page_width,
            page_height=page.page_height,
        ))

    pole_ids = sorted({
        pole_id
        for item in evidence
        for pole_id in (item.pole_id, item.from_pole_id, item.to_pole_id)
        if pole_id
    })
    for item in evidence:
        match_id = item.pole_id or item.from_pole_id
        matched_asset = assets_by_pole_id.get(match_id) if match_id else None
        db.add(PdfPoleEvidence(
            document_id=document.id,
            page_number=item.page_number,
            evidence_type=item.evidence_type,
            pole_id=item.pole_id,
            external_eid=item.external_eid,
            from_pole_id=item.from_pole_id,
            to_pole_id=item.to_pole_id,
            span_length_ft=item.span_length_ft,
            raw_text=item.raw_text,
            bbox_json=json.dumps(item.bbox),
            confidence=item.confidence,
            review_status="OPEN",
            matched_asset_id=matched_asset.id if matched_asset else None,
        ))

    document.processing_status = "PARSED"
    db.commit()

    def evidence_json(item) -> dict:
        return {
            "type": item.evidence_type,
            "page_number": item.page_number,
            "pole_id": item.pole_id,
            "external_eid": item.external_eid,
            "from_pole_id": item.from_pole_id,
            "to_pole_id": item.to_pole_id,
            "span_length_ft": item.span_length_ft,
            "raw_text": item.raw_text,
            "bbox": list(item.bbox),
            "confidence": item.confidence,
        }

    matched = [
        {
            "pole_id": pole_id,
            "asset_id": str(assets_by_pole_id[pole_id].id),
            "asset_name": assets_by_pole_id[pole_id].name,
            "confirmed_coordinates": (
                assets_by_pole_id[pole_id].longitude is not None
                and assets_by_pole_id[pole_id].latitude is not None
            ),
        }
        for pole_id in pole_ids if pole_id in assets_by_pole_id
    ]
    unmatched = [pole_id for pole_id in pole_ids if pole_id not in assets_by_pole_id]
    return {
        "dry_run": True,
        "assets_created": 0,
        "document": {
            "id": str(document.id),
            "project_id": str(document.project_id),
            "filename": document.filename,
            "sha256": document.sha256,
            "processing_status": document.processing_status,
            "duplicate": duplicate,
        },
        "summary": {
            "pages": len(pages),
            "pages_with_native_text": sum(bool(page.raw_text.strip()) for page in pages),
            "pole_ids": len(pole_ids),
            "spans": sum(item.evidence_type == "SPAN" for item in evidence),
            "anchors": sum(item.evidence_type == "ANCHOR" for item in evidence),
            "matched": len(matched),
            "unmatched": len(unmatched),
        },
        "pole_ids": pole_ids,
        "poles": [evidence_json(item) for item in evidence if item.evidence_type == "POLE_ID"],
        "spans": [evidence_json(item) for item in evidence if item.evidence_type == "SPAN"],
        "anchors": [evidence_json(item) for item in evidence if item.evidence_type == "ANCHOR"],
        "matched": matched,
        "unmatched": unmatched,
    }


def _pdf_document(db: Session, document_id: uuid.UUID) -> Document:
    document = db.get(Document, document_id)
    if document is None or document.document_type != "PDF":
        raise HTTPException(status_code=404, detail="PDF document not found.")
    return document


@router.post("/{document_id}/resolve", response_model=ResolutionReport)
def resolve_pdf_document(
    document_id: uuid.UUID,
    payload: DocumentResolutionRequest,
    db: Session = Depends(get_db),
) -> dict:
    document = _pdf_document(db, document_id)
    if not payload.dry_run:
        db.scalar(select(Project).where(Project.id == document.project_id).with_for_update())
    report = resolve_pole_entities(
        db,
        document.project_id,
        document_id=document.id,
        dry_run=payload.dry_run,
    )
    if not payload.dry_run:
        db.commit()
    return report


@router.post("/{document_id}/commit", response_model=CommitReport)
def commit_pdf_document(
    document_id: uuid.UUID,
    payload: CommitRequest,
    db: Session = Depends(get_db),
) -> dict:
    document = _pdf_document(db, document_id)
    db.scalar(select(Project).where(Project.id == document.project_id).with_for_update())
    resolution = resolve_pole_entities(
        db,
        document.project_id,
        document_id=document.id,
        dry_run=False,
    )
    relationships = commit_relationships(db, document.project_id, document.id)
    db.commit()
    return {
        "document_id": str(document.id),
        "project_id": str(document.project_id),
        "assets_created": 0,
        "entity_resolution": resolution,
        "relationships": relationships,
    }


@router.get("/{document_id}/workspace", response_model=PdfWorkspaceResponse)
def pdf_workspace(
    document_id: uuid.UUID,
    evidence_type: str | None = None,
    resolution_status: str | None = None,
    page: int | None = Query(default=None, ge=1),
    min_confidence: float | None = Query(default=None, ge=0, le=1),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> dict:
    document = _pdf_document(db, document_id)
    statement = select(PdfPoleEvidence).where(PdfPoleEvidence.document_id == document.id)
    if evidence_type:
        statement = statement.where(PdfPoleEvidence.evidence_type == evidence_type)
    if page:
        statement = statement.where(PdfPoleEvidence.page_number == page)
    if min_confidence is not None:
        statement = statement.where(PdfPoleEvidence.confidence >= min_confidence)
    evidence = list(db.scalars(statement.order_by(PdfPoleEvidence.page_number, PdfPoleEvidence.id)))

    evidence_ids = [item.id for item in evidence]
    sources = list(db.scalars(select(PoleEntitySource).where(
        PoleEntitySource.source_type == "PDF_EVIDENCE",
        PoleEntitySource.source_id.in_(evidence_ids),
    ))) if evidence_ids else []
    entity_ids = {item.pole_entity_id for item in sources}
    entities = {
        item.id: item for item in db.scalars(select(PoleEntity).where(
            PoleEntity.project_id == document.project_id,
            PoleEntity.id.in_(entity_ids),
        ))
    } if entity_ids else {}
    sources_by_evidence: dict[uuid.UUID, list[PoleEntitySource]] = {}
    for source in sources:
        sources_by_evidence.setdefault(source.source_id, []).append(source)
    asset_sources = list(db.scalars(select(PoleEntitySource).where(
        PoleEntitySource.pole_entity_id.in_(entity_ids),
        PoleEntitySource.source_type == "ASSET",
    ))) if entity_ids else []
    asset_by_entity = {item.pole_entity_id: item.source_id for item in asset_sources}

    def serialize(item: PdfPoleEvidence) -> dict:
        item_sources = sources_by_evidence.get(item.id, [])
        item_entities = [entities[source.pole_entity_id] for source in item_sources if source.pole_entity_id in entities]
        statuses = {entity.resolution_status for entity in item_entities}
        status = "UNRESOLVED" if not statuses else (next(iter(statuses)) if len(statuses) == 1 else "AMBIGUOUS")
        matched_source = next((asset_by_entity.get(entity.id) for entity in item_entities if asset_by_entity.get(entity.id)), None)
        return {
            "id": str(item.id),
            "type": item.evidence_type,
            "page_number": item.page_number,
            "pole_id": item.pole_id,
            "external_eid": item.external_eid,
            "from_pole_id": item.from_pole_id,
            "to_pole_id": item.to_pole_id,
            "span_length_ft": item.span_length_ft,
            "raw_text": item.raw_text,
            "bbox": json.loads(item.bbox_json),
            "confidence": item.confidence,
            "entity_ids": [str(entity.id) for entity in item_entities],
            "resolution_status": status,
            "matched_asset_id": str(matched_source) if matched_source else None,
            "coordinates_available": any(
                entity.latitude is not None and entity.longitude is not None for entity in item_entities
            ),
            "review_status": item.review_status,
        }

    serialized = [serialize(item) for item in evidence]
    if resolution_status:
        serialized = [item for item in serialized if item["resolution_status"] == resolution_status]
    total = len(serialized)
    pages = db.scalar(select(func.count()).select_from(PdfPageText).where(
        PdfPageText.document_id == document.id
    )) or 0
    selected_page = page or (serialized[0]["page_number"] if serialized else 1)
    page_record = db.scalar(select(PdfPageText).where(
        PdfPageText.document_id == document.id,
        PdfPageText.page_number == selected_page,
    ))
    return {
        "document": {
            "id": str(document.id),
            "project_id": str(document.project_id),
            "filename": document.filename,
            "sha256": document.sha256,
            "processing_status": document.processing_status,
            "duplicate": False,
        },
        "pages": pages,
        "items": serialized[offset:offset + limit],
        "total": total,
        "offset": offset,
        "limit": limit,
        "page_width": page_record.page_width if page_record else None,
        "page_height": page_record.page_height if page_record else None,
    }


def _render_page(content: bytes, page_number: int) -> bytes:
    pdf = pdfium.PdfDocument(content)
    if page_number < 1 or page_number > len(pdf):
        raise ValueError("PDF page not found.")
    page = pdf[page_number - 1]
    width, height = page.get_size()
    scale = 1.5
    if width * height * scale * scale > settings.pdf_max_render_pixels:
        raise ValueError("PDF page exceeds the rendering pixel limit.")
    image = page.render(scale=scale).to_pil()
    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()


@router.get("/{document_id}/pages/{page_number}.png")
async def render_pdf_page(
    document_id: uuid.UUID,
    page_number: int,
    db: Session = Depends(get_db),
) -> Response:
    document = _pdf_document(db, document_id)
    blob = db.scalar(select(DocumentBlob).where(DocumentBlob.document_id == document.id))
    if blob is None:
        raise HTTPException(status_code=404, detail="Stored PDF content not found.")
    try:
        content = await asyncio.wait_for(
            run_in_threadpool(_render_page, blob.content, page_number),
            timeout=min(settings.pdf_extraction_timeout_seconds, 30),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except asyncio.TimeoutError as exc:
        raise HTTPException(status_code=504, detail="PDF page rendering timed out.") from exc
    except Exception as exc:
        raise HTTPException(status_code=422, detail="Unable to render PDF page.") from exc
    return Response(content=content, media_type="image/png", headers={"Cache-Control": "private, max-age=300"})


@router.patch("/{document_id}/evidence/{evidence_id}/review")
def mark_evidence_review(
    document_id: uuid.UUID,
    evidence_id: uuid.UUID,
    payload: EvidenceReviewRequest,
    db: Session = Depends(get_db),
) -> dict:
    document = _pdf_document(db, document_id)
    if payload.status not in {"OPEN", "NEEDS_REVIEW", "REVIEWED"}:
        raise HTTPException(status_code=422, detail="Unsupported evidence review status.")
    item = db.get(PdfPoleEvidence, evidence_id)
    if item is None or item.document_id != document.id:
        raise HTTPException(status_code=404, detail="PDF evidence not found.")
    item.review_status = payload.status
    db.commit()
    return {"id": str(item.id), "review_status": item.review_status}


@router.post("/{document_id}/compare")
def compare_pdf_document(document_id: uuid.UUID, db: Session = Depends(get_db)) -> dict:
    document = _pdf_document(db, document_id)
    conflicts = compare_pdf_to_kmz(db, document.project_id, document.id)
    return {
        "document_id": str(document.id),
        "conflicts_created": len(conflicts),
        "conflicts": [
            {
                "id": str(item.id),
                "conflict_type": item.conflict_type,
                "severity": item.severity,
                "source_page": item.source_page,
                "summary": item.summary,
            }
            for item in conflicts
        ],
    }
