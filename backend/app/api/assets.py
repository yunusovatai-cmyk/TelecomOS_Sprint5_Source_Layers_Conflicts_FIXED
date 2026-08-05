from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db.deps import get_db
from app.models.asset import Asset
from app.schemas.asset import AssetRead, AssetUpdate

router = APIRouter(prefix="/assets", tags=["assets"])


@router.get("", response_model=list[AssetRead])
def list_assets(
    project_id: str | None = None,
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
