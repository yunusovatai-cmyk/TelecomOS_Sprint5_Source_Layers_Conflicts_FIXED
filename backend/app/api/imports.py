from __future__ import annotations

import json
import re
from collections import Counter
from time import perf_counter

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.deps import get_db
from app.import_engine.asset_classifier import classify_asset, infer_status
from app.import_engine.kmz_importer import parse_kmz
from app.models.asset import Asset
from app.models.project import Project

router = APIRouter(prefix="/imports", tags=["imports"])


def _project_code(project_name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "-", project_name).strip("-").upper()
    return (cleaned[:48] or "KMZ-PROJECT") + "-KMZ"


@router.post("/kmz", status_code=status.HTTP_201_CREATED)
async def import_kmz(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> dict:
    filename = file.filename or "project.kmz"
    if not filename.lower().endswith(".kmz"):
        raise HTTPException(status_code=400, detail="Only .kmz files are supported.")

    started = perf_counter()
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded KMZ file is empty.")

    try:
        parsed = parse_kmz(content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    code = _project_code(parsed.project_name)
    project = db.scalar(select(Project).where(Project.project_code == code))
    if project is None:
        project = Project(
            project_code=code,
            name=parsed.project_name,
            status="ACTIVE",
        )
        db.add(project)
        db.flush()

    # Idempotent re-import for this first production slice:
    # remove prior imported assets for the same project.
    prior_assets = list(db.scalars(select(Asset).where(Asset.project_id == project.id)))
    for asset in prior_assets:
        db.delete(asset)
    db.flush()

    counts: Counter[str] = Counter()
    imported = 0

    for feature in parsed.features:
        asset_type = classify_asset(feature)
        asset_status, issue = infer_status(feature)

        longitude = None
        latitude = None
        geometry_json = None

        if feature.geometry_type == "Point":
            longitude = float(feature.coordinates[0])
            latitude = float(feature.coordinates[1])
        else:
            geometry_json = json.dumps({
                "type": feature.geometry_type,
                "coordinates": feature.coordinates,
            })

        db.add(
            Asset(
                project_id=project.id,
                asset_type=asset_type,
                name=feature.name,
                status=asset_status,
                longitude=longitude,
                latitude=latitude,
                geometry_type=feature.geometry_type,
                geometry_json=geometry_json,
                issue=issue,
            )
        )
        counts[asset_type] += 1
        imported += 1

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Import could not be committed.") from exc

    db.refresh(project)
    duration_ms = round((perf_counter() - started) * 1000, 2)

    return {
        "project": {
            "id": str(project.id),
            "project_code": project.project_code,
            "name": project.name,
            "status": project.status,
        },
        "source_file": filename,
        "placemarks": len(parsed.features),
        "imported": imported,
        "asset_types": dict(counts),
        "warnings": parsed.warnings,
        "errors": parsed.errors,
        "duration_ms": duration_ms,
    }
