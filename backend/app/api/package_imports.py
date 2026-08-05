from __future__ import annotations
import hashlib, json, re, uuid
from collections import Counter
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.db.deps import get_db
from app.import_engine.asset_classifier import classify_asset, infer_status
from app.import_engine.kmz_importer import parse_kml_content, parse_kmz
from app.models.asset import Asset
from app.models.document import Document
from app.models.project import Project
from app.services.document_classifier import classify_document, extract_revision

router = APIRouter(prefix="/package-imports", tags=["package-imports"])

def _code_from_name(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "-", name).strip("-").upper()
    return (cleaned[:48] or "PROJECT") + "-PKG"

@router.post("")
async def import_project_package(
    files: list[UploadFile] = File(...),
    project_id: str | None = Form(default=None),
    project_name: str | None = Form(default=None),
    db: Session = Depends(get_db),
) -> dict:
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded.")
    project = None
    if project_id:
        project = db.get(Project, uuid.UUID(project_id))
    if project is None:
        resolved_name = (project_name or "Imported Project Package").strip()
        code = _code_from_name(resolved_name)
        project = db.scalar(select(Project).where(Project.project_code == code))
        if project is None:
            project = Project(project_code=code, name=resolved_name, status="ACTIVE")
            db.add(project); db.flush()

    doc_counts, asset_counts = Counter(), Counter()
    registered, warnings = [], []

    for upload in files:
        filename = upload.filename or "unnamed"
        content = await upload.read()
        digest = hashlib.sha256(content).hexdigest()
        dtype = classify_document(filename, upload.content_type)
        revision = extract_revision(filename)

        existing = db.scalar(select(Document).where(Document.project_id == project.id, Document.sha256 == digest))
        if existing:
            warnings.append(f"Duplicate skipped: {filename}")
            registered.append({"id": str(existing.id), "filename": existing.filename, "document_type": existing.document_type, "duplicate": True, "assets_created": 0})
            continue

        document = Document(
            project_id=project.id, filename=filename, document_type=dtype, revision=revision,
            sha256=digest, mime_type=upload.content_type, size_bytes=len(content), processing_status="REGISTERED"
        )
        db.add(document); db.flush()

        created = 0
        if dtype in {"KMZ","KML"}:
            try:
                parsed = parse_kmz(content) if dtype == "KMZ" else parse_kml_content(content)
                for feature in parsed.features:
                    atype = classify_asset(feature)
                    status, issue = infer_status(feature)
                    lon = lat = None
                    geometry_json = None
                    if feature.geometry_type == "Point":
                        lon, lat = float(feature.coordinates[0]), float(feature.coordinates[1])
                    else:
                        geometry_json = json.dumps({"type": feature.geometry_type, "coordinates": feature.coordinates})
                    db.add(Asset(
                        project_id=project.id, asset_type=atype, name=feature.name, status=status,
                        longitude=lon, latitude=lat, geometry_type=feature.geometry_type,
                        geometry_json=geometry_json, issue=issue, source_document_id=document.id
                    ))
                    asset_counts[atype] += 1; created += 1
                document.processing_status = "PARSED"
                warnings.extend(parsed.warnings)
            except Exception as exc:
                document.processing_status = "ERROR"
                warnings.append(f"{filename}: {exc}")

        doc_counts[dtype] += 1
        registered.append({
            "id": str(document.id), "filename": filename, "document_type": dtype,
            "revision": revision, "duplicate": False, "assets_created": created,
            "processing_status": document.processing_status,
        })

    db.commit()
    return {
        "project": {"id": str(project.id), "project_code": project.project_code, "name": project.name},
        "documents_registered": sum(1 for x in registered if not x.get("duplicate")),
        "document_types": dict(doc_counts),
        "assets_created": sum(asset_counts.values()),
        "asset_types": dict(asset_counts),
        "warnings": warnings,
        "documents": registered,
    }
