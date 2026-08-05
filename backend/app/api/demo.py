from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.deps import get_db
from app.models.asset import Asset
from app.models.project import Project
from app.schemas.asset import AssetRead
from app.schemas.project import ProjectRead

router = APIRouter(prefix="/demo", tags=["demo"])


@router.post("/load")
def load_demo(db: Session = Depends(get_db)) -> dict:
    project = db.scalar(select(Project).where(Project.project_code == "DEMO-001"))
    if project is None:
        project = Project(
            project_code="DEMO-001",
            name="TelecomOS Demo Network",
            status="ACTIVE",
        )
        db.add(project)
        db.flush()

    existing = list(db.scalars(select(Asset).where(Asset.project_id == project.id)))
    if not existing:
        demo_assets = [
            Asset(
                project_id=project.id,
                asset_type="POLE",
                name="Pole 217",
                status="VERIFIED",
                longitude=-121.611595,
                latitude=39.010965,
                geometry_type="Point",
            ),
            Asset(
                project_id=project.id,
                asset_type="POLE",
                name="Pole 218",
                status="REVIEW",
                longitude=-121.611180,
                latitude=39.010760,
                geometry_type="Point",
                issue="Coordinate mismatch",
            ),
            Asset(
                project_id=project.id,
                asset_type="HANDHOLE",
                name="HH-12",
                status="REVIEW",
                longitude=-121.610810,
                latitude=39.010530,
                geometry_type="Point",
                issue="Missing photo",
            ),
            Asset(
                project_id=project.id,
                asset_type="UG_SEGMENT",
                name="UG Segment 44",
                status="REVIEW",
                geometry_type="LineString",
                geometry_json=json.dumps({
                    "type": "LineString",
                    "coordinates": [
                        [-121.611595, 39.010965],
                        [-121.611180, 39.010760],
                        [-121.610810, 39.010530],
                    ],
                }),
                issue="Permit verification required",
            ),
            Asset(
                project_id=project.id,
                asset_type="AERIAL_SPAN",
                name="Aerial Span 18",
                status="VERIFIED",
                geometry_type="LineString",
                geometry_json=json.dumps({
                    "type": "LineString",
                    "coordinates": [
                        [-121.611595, 39.010965],
                        [-121.611180, 39.010760],
                    ],
                }),
            ),
        ]
        db.add_all(demo_assets)

    db.commit()
    db.refresh(project)
    assets = list(db.scalars(select(Asset).where(Asset.project_id == project.id)))
    return {
        "project": ProjectRead.model_validate(project),
        "assets": [AssetRead.model_validate(asset) for asset in assets],
    }
