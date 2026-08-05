from __future__ import annotations

import hashlib
import io
import json
import mimetypes
import re
import uuid
import zipfile
from collections import Counter
from dataclasses import dataclass
from pathlib import PurePosixPath

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

MAX_PACKAGE_FILES = 1_000
MAX_PACKAGE_DEPTH = 5
MAX_FILE_SIZE = 25 * 1024 * 1024
MAX_TOTAL_SIZE = 100 * 1024 * 1024
MAX_COMPRESSION_RATIO = 100


class UnsafePackageError(ValueError):
    pass


@dataclass(frozen=True)
class PackageFile:
    filename: str
    content: bytes
    content_type: str | None


@dataclass
class _PackageBudget:
    files: int = 0
    total_size: int = 0


def _safe_member_name(name: str) -> str:
    if not name or "\\" in name or name.startswith("/"):
        raise UnsafePackageError(f"Unsafe archive path: {name!r}")
    path = PurePosixPath(name)
    if any(part in {"", ".", ".."} for part in path.parts):
        raise UnsafePackageError(f"Unsafe archive path: {name!r}")
    return path.as_posix()


def _is_symlink(info: zipfile.ZipInfo) -> bool:
    return (info.external_attr >> 16) & 0o170000 == 0o120000


def _extract_zip(
    content: bytes,
    *,
    prefix: str = "",
    depth: int = 0,
    budget: _PackageBudget | None = None,
) -> list[PackageFile]:
    if depth > MAX_PACKAGE_DEPTH:
        raise UnsafePackageError(f"Archive nesting exceeds {MAX_PACKAGE_DEPTH} levels.")
    budget = budget or _PackageBudget()
    extracted: list[PackageFile] = []

    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            entries = [info for info in archive.infolist() if not info.is_dir()]
            for info in entries:
                _safe_member_name(info.filename)
                if info.flag_bits & 0x1:
                    raise UnsafePackageError(f"Encrypted archive member is not supported: {info.filename}")
                if _is_symlink(info):
                    raise UnsafePackageError(f"Archive symlink is not allowed: {info.filename}")
                if info.file_size > MAX_FILE_SIZE:
                    raise UnsafePackageError(f"Archive member is too large: {info.filename}")
                if info.file_size / max(info.compress_size, 1) > MAX_COMPRESSION_RATIO:
                    raise UnsafePackageError(f"Suspicious compression ratio for: {info.filename}")

            for info in entries:
                member_name = _safe_member_name(info.filename)
                full_name = f"{prefix}/{member_name}" if prefix else member_name
                payload = archive.read(info)
                if len(payload) != info.file_size or len(payload) > MAX_FILE_SIZE:
                    raise UnsafePackageError(f"Invalid expanded size for: {full_name}")

                budget.files += 1
                budget.total_size += len(payload)
                if budget.files > MAX_PACKAGE_FILES:
                    raise UnsafePackageError(f"Archive contains more than {MAX_PACKAGE_FILES} files.")
                if budget.total_size > MAX_TOTAL_SIZE:
                    raise UnsafePackageError("Archive expanded size exceeds the allowed total.")

                if PurePosixPath(member_name).suffix.lower() == ".zip":
                    extracted.extend(_extract_zip(payload, prefix=full_name, depth=depth + 1, budget=budget))
                else:
                    content_type, _ = mimetypes.guess_type(member_name)
                    extracted.append(PackageFile(full_name, payload, content_type))
    except zipfile.BadZipFile as exc:
        raise UnsafePackageError("Uploaded file is not a valid ZIP archive.") from exc
    except (RuntimeError, NotImplementedError) as exc:
        raise UnsafePackageError(f"Archive cannot be safely read: {exc}") from exc

    return extracted

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
    registered, warnings, errors = [], [], []
    found = parsed_count = skipped = 0

    for upload in files:
        filename = upload.filename or "unnamed"
        content = await upload.read()
        dtype = classify_document(filename, upload.content_type)

        if dtype == "PROJECT_PACKAGE":
            try:
                candidates = _extract_zip(content)
                found += len(candidates)
            except UnsafePackageError as exc:
                errors.append(f"{filename}: {exc}")
                continue
        else:
            candidates = [PackageFile(filename, content, upload.content_type)]
            found += 1

        for candidate in candidates:
            candidate_type = classify_document(candidate.filename, candidate.content_type)
            digest = hashlib.sha256(candidate.content).hexdigest()
            revision = extract_revision(candidate.filename)

            existing = db.scalar(select(Document).where(Document.project_id == project.id, Document.sha256 == digest))
            if existing:
                skipped += 1
                warnings.append(f"Duplicate skipped: {candidate.filename}")
                registered.append({"id": str(existing.id), "filename": existing.filename, "document_type": existing.document_type, "duplicate": True, "assets_created": 0})
                continue

            document = Document(
                project_id=project.id, filename=candidate.filename, document_type=candidate_type,
                revision=revision, sha256=digest, mime_type=candidate.content_type,
                size_bytes=len(candidate.content), processing_status="REGISTERED"
            )
            db.add(document); db.flush()

            created = 0
            if candidate_type in {"KMZ", "KML"}:
                try:
                    parsed = parse_kmz(candidate.content) if candidate_type == "KMZ" else parse_kml_content(candidate.content)
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
                        asset_counts[atype] += 1
                        created += 1
                    document.processing_status = "PARSED"
                    parsed_count += 1
                    warnings.extend(parsed.warnings)
                except Exception as exc:
                    document.processing_status = "ERROR"
                    errors.append(f"{candidate.filename}: {exc}")

            doc_counts[candidate_type] += 1
            registered.append({
                "id": str(document.id), "filename": candidate.filename, "document_type": candidate_type,
                "revision": revision, "duplicate": False, "assets_created": created,
                "processing_status": document.processing_status,
            })

    db.commit()
    return {
        "project": {"id": str(project.id), "project_code": project.project_code, "name": project.name},
        "report": {
            "found": found,
            "registered": sum(1 for item in registered if not item.get("duplicate")),
            "parsed": parsed_count,
            "skipped": skipped,
            "errors": errors,
        },
        "documents_registered": sum(1 for x in registered if not x.get("duplicate")),
        "document_types": dict(doc_counts),
        "assets_created": sum(asset_counts.values()),
        "asset_types": dict(asset_counts),
        "warnings": warnings,
        "errors": errors,
        "documents": registered,
    }
