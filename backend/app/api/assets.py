from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db.deps import get_db
from app.models.asset import Asset
from app.models.document import Document
from app.models.pdf_extraction import PdfPoleEvidence
from app.models.pole_entity import PoleEntity, PoleEntitySource
from app.schemas.asset import AssetRead, AssetUpdate

router = APIRouter(prefix="/assets", tags=["assets"])


@router.get("", response_model=list[AssetRead])
def list_assets(
    project_id: uuid.UUID | None = None,
    query: str | None = None,
    asset_type: str | None = None,
    status: str | None = None,
    db: Session = Depends(get_db),
) -> list[Asset]:
    statement = select(Asset).order_by(Asset.created_at.asc())

    if project_id:
        statement = statement.where(Asset.project_id == project_id)

    if query:
        like = f"%{query.strip()}%"
        statement = statement.where(
            or_(
                Asset.name.ilike(like),
                Asset.issue.ilike(like),
            )
        )

    if asset_type:
        statement = statement.where(Asset.asset_type == asset_type)

    if status:
        statement = statement.where(Asset.status == status)

    return list(db.scalars(statement))


@router.get("/{asset_id}/pdf-evidence")
def asset_pdf_evidence(asset_id: uuid.UUID, db: Session = Depends(get_db)) -> dict:
    asset = db.get(Asset, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found.")
    asset_sources = list(db.scalars(select(PoleEntitySource).where(
        PoleEntitySource.source_type == "ASSET",
        PoleEntitySource.source_id == asset.id,
    )))
    entity_ids = {source.pole_entity_id for source in asset_sources}
    entities = {
        item.id: item for item in db.scalars(select(PoleEntity).where(
            PoleEntity.project_id == asset.project_id,
            PoleEntity.id.in_(entity_ids),
        ))
    } if entity_ids else {}
    pdf_sources = list(db.scalars(select(PoleEntitySource).where(
        PoleEntitySource.pole_entity_id.in_(entities),
        PoleEntitySource.source_type == "PDF_EVIDENCE",
    ))) if entities else []
    evidence_ids = [source.source_id for source in pdf_sources]
    evidence = {
        item.id: item for item in db.scalars(select(PdfPoleEvidence).where(
            PdfPoleEvidence.id.in_(evidence_ids),
        ))
    } if evidence_ids else {}
    document_ids = {item.document_id for item in evidence.values()}
    documents = {
        item.id: item for item in db.scalars(select(Document).where(
            Document.project_id == asset.project_id,
            Document.id.in_(document_ids),
        ))
    } if document_ids else {}
    items = []
    for source in pdf_sources:
        item = evidence.get(source.source_id)
        if item is None or item.document_id not in documents:
            continue
        items.append({
            "id": str(item.id),
            "entity_id": str(source.pole_entity_id),
            "document_id": str(item.document_id),
            "document": documents[item.document_id].filename,
            "page": item.page_number,
            "type": item.evidence_type,
            "raw_text": item.raw_text,
            "confidence": item.confidence,
            "review_status": item.review_status,
        })
    return {"asset_id": str(asset.id), "items": items, "total": len(items)}


@router.get("/{asset_id}", response_model=AssetRead)
def read_asset(asset_id: uuid.UUID, db: Session = Depends(get_db)) -> Asset:
    asset = db.get(Asset, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found.")
    return asset


@router.patch("/{asset_id}", response_model=AssetRead)
def update_asset(
    asset_id: uuid.UUID,
    payload: AssetUpdate,
    db: Session = Depends(get_db),
) -> Asset:
    asset = db.get(Asset, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found.")

    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(asset, field, value)

    db.commit()
    db.refresh(asset)
    return asset
