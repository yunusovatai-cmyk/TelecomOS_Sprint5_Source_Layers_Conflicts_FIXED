from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.deps import get_db
from app.models.pole_entity import PoleEntity, PoleRelationship
from app.schemas.pole_entity import PoleRelationshipPage, PoleRelationshipRead
from app.services.pole_entity_resolution import relationship_geojson

router = APIRouter(prefix="/pole-relationships", tags=["pole-relationships"])


def _serialize(item: PoleRelationship, entities: dict[uuid.UUID, PoleEntity]) -> dict:
    return {
        column.name: getattr(item, column.name)
        for column in PoleRelationship.__table__.columns
    } | {"derived_geojson": relationship_geojson(item, entities)}


@router.get("", response_model=PoleRelationshipPage)
def list_relationships(
    project_id: uuid.UUID,
    status: str | None = None,
    relationship_type: str | None = None,
    source_document_id: uuid.UUID | None = None,
    page: int | None = Query(default=None, ge=1),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> dict:
    statement = select(PoleRelationship).where(PoleRelationship.project_id == project_id)
    if status:
        statement = statement.where(PoleRelationship.resolution_status == status)
    if relationship_type:
        statement = statement.where(PoleRelationship.relationship_type == relationship_type)
    if source_document_id:
        statement = statement.where(PoleRelationship.source_document_id == source_document_id)
    if page:
        statement = statement.where(PoleRelationship.source_page == page)
    total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    items = list(db.scalars(statement.order_by(PoleRelationship.source_page, PoleRelationship.id).offset(offset).limit(limit)))
    entity_ids = {
        entity_id for item in items
        for entity_id in (item.from_pole_entity_id, item.to_pole_entity_id)
        if entity_id
    }
    entities = {
        item.id: item for item in db.scalars(select(PoleEntity).where(
            PoleEntity.project_id == project_id,
            PoleEntity.id.in_(entity_ids),
        ))
    } if entity_ids else {}
    return {"items": [_serialize(item, entities) for item in items], "total": total, "offset": offset, "limit": limit}


@router.get("/{relationship_id}", response_model=PoleRelationshipRead)
def read_relationship(relationship_id: uuid.UUID, db: Session = Depends(get_db)) -> dict:
    item = db.get(PoleRelationship, relationship_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Pole relationship not found.")
    entity_ids = [value for value in (item.from_pole_entity_id, item.to_pole_entity_id) if value]
    entities = {entity.id: entity for entity in db.scalars(select(PoleEntity).where(
        PoleEntity.project_id == item.project_id,
        PoleEntity.id.in_(entity_ids),
    ))} if entity_ids else {}
    return _serialize(item, entities)
