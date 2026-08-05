from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.deps import get_db
from app.models.conflict import Conflict
from app.schemas.conflict import ConflictDecision, ConflictRead
from app.services.conflict_engine import rebuild_conflicts

router = APIRouter(prefix="/conflicts", tags=["conflicts"])


@router.post("/rebuild", response_model=list[ConflictRead])
def rebuild(project_id: str, db: Session = Depends(get_db)) -> list[Conflict]:
    return rebuild_conflicts(project_id, db)


@router.get("", response_model=list[ConflictRead])
def list_conflicts(project_id: str, db: Session = Depends(get_db)) -> list[Conflict]:
    return list(
        db.scalars(
            select(Conflict)
            .where(Conflict.project_id == project_id)
            .order_by(Conflict.created_at.desc())
        )
    )


@router.patch("/{conflict_id}", response_model=ConflictRead)
def decide_conflict(
    conflict_id: uuid.UUID,
    payload: ConflictDecision,
    db: Session = Depends(get_db),
) -> Conflict:
    conflict = db.get(Conflict, conflict_id)
    if conflict is None:
        raise HTTPException(status_code=404, detail="Conflict not found.")

    conflict.decision = payload.decision
    conflict.decision_reason = payload.decision_reason
    conflict.status = "RESOLVED" if payload.decision != "NEEDS_REVIEW" else "OPEN"

    db.commit()
    db.refresh(conflict)
    return conflict
