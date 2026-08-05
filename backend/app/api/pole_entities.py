from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.db.deps import get_db
from app.models.asset import Asset
from app.models.pole_entity import PoleEntity, PoleEntityAudit, PoleEntitySource
from app.models.project import Project
from app.schemas.pole_entity import (
    ManualMatchRequest,
    PoleEntityPage,
    PoleEntityRead,
    PoleEntitySourceRead,
    ResolutionReport,
    ResolutionRequest,
    UnmatchRequest,
)
from app.services.pole_entity_resolution import (
    asset_identifiers,
    refresh_relationship_statuses,
    resolve_pole_entities,
    snapshot_json,
)

router = APIRouter(prefix="/pole-entities", tags=["pole-entities"])


def _entity_or_404(db: Session, entity_id: uuid.UUID, *, for_update: bool = False) -> PoleEntity:
    statement = select(PoleEntity).where(PoleEntity.id == entity_id)
    if for_update:
        statement = statement.with_for_update()
    entity = db.scalar(statement)
    if entity is None:
        raise HTTPException(status_code=404, detail="Pole entity not found.")
    return entity


@router.get("", response_model=PoleEntityPage)
def list_pole_entities(
    project_id: uuid.UUID,
    status: str | None = None,
    pole_id: str | None = None,
    matched: bool | None = None,
    has_coordinates: bool | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> dict:
    statement = select(PoleEntity).where(PoleEntity.project_id == project_id)
    if status:
        statement = statement.where(PoleEntity.resolution_status == status)
    if pole_id:
        statement = statement.where(PoleEntity.canonical_pole_id == pole_id.strip())
    if has_coordinates is True:
        statement = statement.where(PoleEntity.latitude.is_not(None), PoleEntity.longitude.is_not(None))
    elif has_coordinates is False:
        statement = statement.where((PoleEntity.latitude.is_(None)) | (PoleEntity.longitude.is_(None)))
    if matched is not None:
        asset_source = select(PoleEntitySource.id).where(
            PoleEntitySource.pole_entity_id == PoleEntity.id,
            PoleEntitySource.source_type == "ASSET",
        ).exists()
        statement = statement.where(asset_source if matched else ~asset_source)

    total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    items = list(db.scalars(statement.order_by(PoleEntity.canonical_pole_id, PoleEntity.id).offset(offset).limit(limit)))
    return {"items": items, "total": total, "offset": offset, "limit": limit}


@router.post("/resolve", response_model=ResolutionReport)
def resolve_all(payload: ResolutionRequest, db: Session = Depends(get_db)) -> dict:
    project_statement = select(Project).where(Project.id == payload.project_id)
    if not payload.dry_run:
        project_statement = project_statement.with_for_update()
    if db.scalar(project_statement) is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    report = resolve_pole_entities(db, payload.project_id, dry_run=payload.dry_run)
    if not payload.dry_run:
        db.commit()
    return report


@router.get("/{entity_id}", response_model=PoleEntityRead)
def read_pole_entity(entity_id: uuid.UUID, db: Session = Depends(get_db)) -> PoleEntity:
    return _entity_or_404(db, entity_id)


@router.get("/{entity_id}/sources", response_model=list[PoleEntitySourceRead])
def list_pole_entity_sources(entity_id: uuid.UUID, db: Session = Depends(get_db)) -> list[PoleEntitySource]:
    entity = _entity_or_404(db, entity_id)
    return list(db.scalars(
        select(PoleEntitySource)
        .where(PoleEntitySource.pole_entity_id == entity.id)
        .order_by(PoleEntitySource.created_at)
    ))

@router.patch("/{entity_id}/manual-match", response_model=PoleEntityRead)
def manual_match(
    entity_id: uuid.UUID,
    payload: ManualMatchRequest,
    db: Session = Depends(get_db),
) -> PoleEntity:
    entity = _entity_or_404(db, entity_id, for_update=True)
    asset = db.scalar(select(Asset).where(Asset.id == payload.asset_id).with_for_update())
    if asset is None or asset.project_id != entity.project_id:
        raise HTTPException(status_code=404, detail="Asset not found in the pole entity project.")
    occupied = db.scalar(select(PoleEntitySource).where(
        PoleEntitySource.source_type == "ASSET",
        PoleEntitySource.source_id == asset.id,
        PoleEntitySource.pole_entity_id != entity.id,
    ))
    if occupied:
        raise HTTPException(status_code=409, detail="Asset is already matched to another pole entity.")

    before = snapshot_json(entity)
    db.execute(delete(PoleEntitySource).where(
        PoleEntitySource.pole_entity_id == entity.id,
        PoleEntitySource.source_type == "ASSET",
    ))
    pole_ids, eids = asset_identifiers(asset)
    entity.latitude = asset.latitude
    entity.longitude = asset.longitude
    entity.geometry_source = "ASSET"
    entity.resolution_status = "MANUAL"
    entity.confidence = 1.0
    if entity.canonical_pole_id is None and len(pole_ids) == 1:
        entity.canonical_pole_id = next(iter(pole_ids))
    if entity.canonical_eid is None and len(eids) == 1:
        entity.canonical_eid = next(iter(eids))
    db.add(PoleEntitySource(
        pole_entity_id=entity.id,
        source_type="ASSET",
        source_id=asset.id,
        source_document_id=asset.source_document_id,
        external_pole_id=entity.canonical_pole_id,
        external_eid=entity.canonical_eid,
        match_method="MANUAL",
        confidence=1.0,
    ))
    db.flush()
    db.add(PoleEntityAudit(
        pole_entity_id=entity.id,
        action="MANUAL_MATCH",
        reason=payload.reason,
        reviewer=payload.reviewer,
        before_json=before,
        after_json=snapshot_json(entity),
    ))
    refresh_relationship_statuses(db, entity.project_id)
    db.commit()
    db.refresh(entity)
    return entity


@router.patch("/{entity_id}/unmatch", response_model=PoleEntityRead)
def unmatch(
    entity_id: uuid.UUID,
    payload: UnmatchRequest,
    db: Session = Depends(get_db),
) -> PoleEntity:
    entity = _entity_or_404(db, entity_id, for_update=True)
    before = snapshot_json(entity)
    db.execute(delete(PoleEntitySource).where(
        PoleEntitySource.pole_entity_id == entity.id,
        PoleEntitySource.source_type == "ASSET",
    ))
    entity.latitude = None
    entity.longitude = None
    entity.geometry_source = None
    entity.resolution_status = "UNRESOLVED"
    entity.confidence = 0.0
    db.flush()
    db.add(PoleEntityAudit(
        pole_entity_id=entity.id,
        action="UNMATCH",
        reason=payload.reason,
        reviewer=payload.reviewer,
        before_json=before,
        after_json=snapshot_json(entity),
    ))
    refresh_relationship_statuses(db, entity.project_id)
    db.commit()
    db.refresh(entity)
    return entity
