import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.deps import get_db
from app.models.asset import Asset
from app.core.config import settings
from app.models.document import Document
from app.models.pdf_extraction import PdfPoleEvidence
from app.models.pole_entity import PoleEntity, PoleEntitySource, PoleRelationship
from app.services.pole_entity_resolution import asset_identifiers
from app.schemas.asset import AssetRead

router = APIRouter(prefix="/review", tags=["review"])


@router.get("/pdf-items")
def list_pdf_review_items(
    project_id: uuid.UUID,
    item_type: str | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> dict:
    entities = list(db.scalars(select(PoleEntity).where(
        PoleEntity.project_id == project_id,
        PoleEntity.resolution_status.in_(("UNRESOLVED", "AMBIGUOUS")),
    )))
    documents = {
        item.id: item for item in db.scalars(select(Document).where(Document.project_id == project_id))
    }
    entity_ids = [item.id for item in entities]
    sources = list(db.scalars(select(PoleEntitySource).where(
        PoleEntitySource.pole_entity_id.in_(entity_ids),
        PoleEntitySource.source_type == "PDF_EVIDENCE",
    ))) if entity_ids else []
    evidence_ids = [item.source_id for item in sources]
    evidence = {
        item.id: item for item in db.scalars(select(PdfPoleEvidence).where(PdfPoleEvidence.id.in_(evidence_ids)))
    } if evidence_ids else {}
    assets = list(db.scalars(select(Asset).where(Asset.project_id == project_id)))
    items = []
    for entity in entities:
        source = next((item for item in sources if item.pole_entity_id == entity.id), None)
        item = evidence.get(source.source_id) if source else None
        candidates = []
        for asset in assets:
            pole_ids, eids = asset_identifiers(asset)
            if entity.canonical_pole_id in pole_ids or entity.canonical_eid in eids:
                candidates.append({"id": str(asset.id), "name": asset.name})
        items.append({
            "id": str(entity.id),
            "type": "AMBIGUOUS_PDF_POLE" if entity.resolution_status == "AMBIGUOUS" else "UNMATCHED_PDF_POLE",
            "pole_id": entity.canonical_pole_id,
            "document_id": str(item.document_id) if item else None,
            "document": documents[item.document_id].filename if item and item.document_id in documents else None,
            "page": item.page_number if item else None,
            "confidence": item.confidence if item else entity.confidence,
            "candidate_assets": candidates,
            "entity_id": str(entity.id),
        })

    for relationship in db.scalars(select(PoleRelationship).where(
        PoleRelationship.project_id == project_id,
        PoleRelationship.resolution_status == "PARTIAL",
    )):
        items.append({
            "id": str(relationship.id),
            "type": "PARTIAL_PDF_SPAN",
            "pole_id": f"{relationship.from_external_pole_id} → {relationship.to_external_pole_id}",
            "document_id": str(relationship.source_document_id),
            "document": documents.get(relationship.source_document_id).filename if documents.get(relationship.source_document_id) else None,
            "page": relationship.source_page,
            "confidence": relationship.confidence,
            "candidate_assets": [],
            "entity_id": None,
        })

    low_confidence = list(db.scalars(
        select(PdfPoleEvidence)
        .join(Document, PdfPoleEvidence.document_id == Document.id)
        .where(
            Document.project_id == project_id,
            PdfPoleEvidence.confidence < settings.pdf_low_confidence_threshold,
        )
    ))
    for item in low_confidence:
        items.append({
            "id": str(item.id),
            "type": "LOW_CONFIDENCE_EXTRACTION",
            "pole_id": item.pole_id or f"{item.from_pole_id or '?'} → {item.to_pole_id or '?'}",
            "document_id": str(item.document_id),
            "document": documents.get(item.document_id).filename if documents.get(item.document_id) else None,
            "page": item.page_number,
            "confidence": item.confidence,
            "candidate_assets": [],
            "entity_id": None,
        })
    if item_type:
        items = [item for item in items if item["type"] == item_type]
    return {"items": items[offset:offset + limit], "total": len(items), "offset": offset, "limit": limit}


@router.get("", response_model=list[AssetRead])
def list_review_items(
    project_id: uuid.UUID | None = None,
    db: Session = Depends(get_db),
) -> list[Asset]:
    statement = select(Asset).where(Asset.status == "REVIEW")
    if project_id:
        statement = statement.where(Asset.project_id == project_id)
    return list(db.scalars(statement.order_by(Asset.created_at.asc())))
