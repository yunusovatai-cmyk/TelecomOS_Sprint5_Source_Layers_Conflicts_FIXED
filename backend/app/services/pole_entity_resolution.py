from __future__ import annotations

import json
import re
import uuid
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.asset import Asset
from app.models.document import Document
from app.models.pdf_extraction import PdfPoleEvidence
from app.models.pole_entity import PoleEntity, PoleEntitySource, PoleRelationship


POLE_ID_RE = re.compile(r"\b(\d{9})\b")
EID_RE = re.compile(r"\bEID\s*(?:ID|NO\.?|#|:)?\s*([A-Z0-9][A-Z0-9_-]{2,63})\b", re.IGNORECASE)


def asset_identifiers(asset: Asset) -> tuple[set[str], set[str]]:
    searchable = " ".join(filter(None, (asset.name, asset.issue)))
    return set(POLE_ID_RE.findall(searchable)), {match.upper() for match in EID_RE.findall(searchable)}


def _evidence_keys(item: PdfPoleEvidence) -> set[tuple[str, str]]:
    keys = set()
    for pole_id in (item.pole_id, item.from_pole_id, item.to_pole_id):
        if pole_id:
            keys.add(("POLE", pole_id))
    if item.external_eid:
        keys.add(("EID", item.external_eid.upper()))
    return keys


def _entity_snapshot(entity: PoleEntity) -> dict:
    return {
        "id": str(entity.id),
        "canonical_pole_id": entity.canonical_pole_id,
        "canonical_eid": entity.canonical_eid,
        "latitude": entity.latitude,
        "longitude": entity.longitude,
        "geometry_source": entity.geometry_source,
        "resolution_status": entity.resolution_status,
        "confidence": entity.confidence,
    }


def resolve_pole_entities(
    db: Session,
    project_id: uuid.UUID,
    *,
    document_id: uuid.UUID | None = None,
    dry_run: bool = False,
) -> dict:
    evidence_statement = (
        select(PdfPoleEvidence)
        .join(Document, PdfPoleEvidence.document_id == Document.id)
        .where(Document.project_id == project_id)
    )
    if document_id:
        evidence_statement = evidence_statement.where(PdfPoleEvidence.document_id == document_id)
    evidence = list(db.scalars(evidence_statement))

    keyed_evidence: dict[tuple[str, str], list[PdfPoleEvidence]] = defaultdict(list)
    for item in evidence:
        for key in _evidence_keys(item):
            keyed_evidence[key].append(item)

    assets = list(db.scalars(select(Asset).where(Asset.project_id == project_id)))
    assets_by_pole: dict[str, list[Asset]] = defaultdict(list)
    assets_by_eid: dict[str, list[Asset]] = defaultdict(list)
    for asset in assets:
        pole_ids, eids = asset_identifiers(asset)
        for pole_id in pole_ids:
            assets_by_pole[pole_id].append(asset)
        for eid in eids:
            assets_by_eid[eid].append(asset)

    entities = list(db.scalars(select(PoleEntity).where(PoleEntity.project_id == project_id)))
    entity_by_pole = {item.canonical_pole_id: item for item in entities if item.canonical_pole_id}
    entity_by_eid = {item.canonical_eid: item for item in entities if item.canonical_eid}
    entity_ids = [item.id for item in entities]
    sources = list(db.scalars(
        select(PoleEntitySource).where(PoleEntitySource.pole_entity_id.in_(entity_ids))
    )) if entity_ids else []
    source_keys = {(item.pole_entity_id, item.source_type, item.source_id) for item in sources}
    asset_owner = {
        item.source_id: item.pole_entity_id for item in sources if item.source_type == "ASSET"
    }

    counts = defaultdict(int)
    entity_results = []
    ordered_keys = sorted(keyed_evidence, key=lambda item: (0 if item[0] == "POLE" else 1, item[1]))
    for key in ordered_keys:
        kind, value = key
        entity = entity_by_pole.get(value) if kind == "POLE" else entity_by_eid.get(value)
        if entity is None and kind == "EID":
            correlated_pole_ids = {
                item.pole_id
                for item in keyed_evidence[key]
                if item.pole_id and item.external_eid and item.external_eid.upper() == value
            }
            correlated_entities = {
                entity_by_pole[pole_id]
                for pole_id in correlated_pole_ids
                if pole_id in entity_by_pole
            }
            if len(correlated_entities) == 1:
                entity = next(iter(correlated_entities))
                if entity.canonical_eid is None:
                    entity.canonical_eid = value
                    entity_by_eid[value] = entity
        if entity:
            counts["reused_entities"] += 1
        else:
            counts["created_entities"] += 1

        candidates = assets_by_pole[value] if kind == "POLE" else assets_by_eid[value]
        match_method = "EXACT_POLE_ID" if kind == "POLE" else "EXACT_EID"
        candidate = candidates[0] if len(candidates) == 1 else None
        if candidate and candidate.id in asset_owner and (entity is None or asset_owner[candidate.id] != entity.id):
            candidate = None
            status = "AMBIGUOUS"
        elif len(candidates) > 1:
            status = "AMBIGUOUS"
        elif candidate:
            status = "RESOLVED"
        else:
            status = "UNRESOLVED"

        if entity and entity.resolution_status == "MANUAL":
            status = "MANUAL"
            candidate = None
        counts[status.lower()] += 1
        entity_results.append({
            "key_type": kind,
            "value": value,
            "status": status,
            "candidate_asset_ids": [str(item.id) for item in candidates],
            "entity_id": str(entity.id) if entity else None,
        })
        if dry_run:
            continue

        if entity is None:
            entity = PoleEntity(
                project_id=project_id,
                canonical_pole_id=value if kind == "POLE" else None,
                canonical_eid=value if kind == "EID" else None,
                resolution_status=status,
                confidence=0.0,
            )
            db.add(entity)
            db.flush()
            entities.append(entity)
            if kind == "POLE":
                entity_by_pole[value] = entity
            else:
                entity_by_eid[value] = entity

        if entity.resolution_status != "MANUAL":
            entity.resolution_status = status
            entity.confidence = 0.99 if status == "RESOLVED" else (0.5 if status == "AMBIGUOUS" else 0.0)
            if candidate:
                entity.latitude = candidate.latitude
                entity.longitude = candidate.longitude
                entity.geometry_source = "ASSET"
            else:
                entity.latitude = None
                entity.longitude = None
                entity.geometry_source = None

        for item in keyed_evidence[key]:
            source_key = (entity.id, "PDF_EVIDENCE", item.id)
            if source_key not in source_keys:
                db.add(PoleEntitySource(
                    pole_entity_id=entity.id,
                    source_type="PDF_EVIDENCE",
                    source_id=item.id,
                    source_document_id=item.document_id,
                    external_pole_id=value if kind == "POLE" else None,
                    external_eid=value if kind == "EID" else None,
                    match_method=match_method if status == "RESOLVED" else status,
                    confidence=item.confidence,
                ))
                source_keys.add(source_key)

        if candidate and entity.resolution_status != "MANUAL":
            source_key = (entity.id, "ASSET", candidate.id)
            if source_key not in source_keys:
                db.add(PoleEntitySource(
                    pole_entity_id=entity.id,
                    source_type="ASSET",
                    source_id=candidate.id,
                    source_document_id=candidate.source_document_id,
                    external_pole_id=value if kind == "POLE" else None,
                    external_eid=value if kind == "EID" else None,
                    match_method=match_method,
                    confidence=0.99,
                ))
                source_keys.add(source_key)
                asset_owner[candidate.id] = entity.id

    if not dry_run:
        db.flush()
    return {
        "project_id": str(project_id),
        "document_id": str(document_id) if document_id else None,
        "dry_run": dry_run,
        "total_evidence": len(evidence),
        "resolved": counts["resolved"],
        "unresolved": counts["unresolved"],
        "ambiguous": counts["ambiguous"],
        "manual": counts["manual"],
        "created_entities": counts["created_entities"],
        "reused_entities": counts["reused_entities"],
        "entities": entity_results,
    }


def _relationship_status(from_entity: PoleEntity | None, to_entity: PoleEntity | None) -> str:
    if (from_entity and from_entity.resolution_status == "AMBIGUOUS") or (
        to_entity and to_entity.resolution_status == "AMBIGUOUS"
    ):
        return "AMBIGUOUS"
    from_known = bool(from_entity and from_entity.latitude is not None and from_entity.longitude is not None)
    to_known = bool(to_entity and to_entity.latitude is not None and to_entity.longitude is not None)
    if from_known and to_known:
        return "RESOLVED"
    if from_known or to_known:
        return "PARTIAL"
    return "UNRESOLVED"


def commit_relationships(db: Session, project_id: uuid.UUID, document_id: uuid.UUID) -> dict:
    evidence = list(db.scalars(
        select(PdfPoleEvidence).where(
            PdfPoleEvidence.document_id == document_id,
            PdfPoleEvidence.evidence_type == "SPAN",
        )
    ))
    entities = list(db.scalars(select(PoleEntity).where(PoleEntity.project_id == project_id)))
    by_pole = {item.canonical_pole_id: item for item in entities if item.canonical_pole_id}
    existing = {
        item.source_evidence_id: item
        for item in db.scalars(select(PoleRelationship).where(
            PoleRelationship.project_id == project_id,
            PoleRelationship.source_document_id == document_id,
        ))
    }
    counts = defaultdict(int)
    for item in evidence:
        from_entity = by_pole.get(item.from_pole_id)
        to_entity = by_pole.get(item.to_pole_id)
        status = _relationship_status(from_entity, to_entity)
        relationship = existing.get(item.id)
        if relationship is None:
            relationship = PoleRelationship(
                project_id=project_id,
                source_document_id=document_id,
                source_evidence_id=item.id,
                from_external_pole_id=item.from_pole_id or "",
                to_external_pole_id=item.to_pole_id or "",
                source_page=item.page_number,
                raw_text=item.raw_text,
                confidence=item.confidence,
            )
            db.add(relationship)
            counts["created"] += 1
        else:
            counts["reused"] += 1
        relationship.from_pole_entity_id = from_entity.id if from_entity else None
        relationship.to_pole_entity_id = to_entity.id if to_entity else None
        relationship.designed_length_ft = item.span_length_ft
        relationship.resolution_status = status
        counts[status.lower()] += 1
    db.flush()
    return {
        "total": len(evidence),
        "created": counts["created"],
        "reused": counts["reused"],
        "resolved": counts["resolved"],
        "partial": counts["partial"],
        "unresolved": counts["unresolved"],
        "ambiguous": counts["ambiguous"],
    }


def refresh_relationship_statuses(db: Session, project_id: uuid.UUID) -> None:
    entities = {item.id: item for item in db.scalars(select(PoleEntity).where(PoleEntity.project_id == project_id))}
    for relationship in db.scalars(select(PoleRelationship).where(PoleRelationship.project_id == project_id)):
        relationship.resolution_status = _relationship_status(
            entities.get(relationship.from_pole_entity_id),
            entities.get(relationship.to_pole_entity_id),
        )


def relationship_geojson(relationship: PoleRelationship, entities: dict[uuid.UUID, PoleEntity]) -> dict | None:
    from_entity = entities.get(relationship.from_pole_entity_id)
    to_entity = entities.get(relationship.to_pole_entity_id)
    if not from_entity or not to_entity:
        return None
    if None in (from_entity.longitude, from_entity.latitude, to_entity.longitude, to_entity.latitude):
        return None
    return {
        "type": "LineString",
        "coordinates": [
            [from_entity.longitude, from_entity.latitude],
            [to_entity.longitude, to_entity.latitude],
        ],
    }


def snapshot_json(entity: PoleEntity) -> str:
    return json.dumps(_entity_snapshot(entity), sort_keys=True)
