import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.deps import get_db
from app.models.asset import Asset
from app.schemas.asset import AssetRead

router = APIRouter(prefix="/review", tags=["review"])


@router.get("", response_model=list[AssetRead])
def list_review_items(
    project_id: uuid.UUID | None = None,
    db: Session = Depends(get_db),
) -> list[Asset]:
    statement = select(Asset).where(Asset.status == "REVIEW")
    if project_id:
        statement = statement.where(Asset.project_id == project_id)
    return list(db.scalars(statement.order_by(Asset.created_at.asc())))
