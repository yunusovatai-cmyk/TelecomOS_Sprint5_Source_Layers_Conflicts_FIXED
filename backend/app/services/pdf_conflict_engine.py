from __future__ import annotations

import json
import math
import uuid

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.asset import Asset
from app.models.conflict import Conflict
from app.models.pdf_extraction import PdfPoleEvidence
from app.models.pole_entity import PoleEntity, PoleEntitySource, PoleRelationship
from app.services.pole_entity_resolution import asset_identifiers


PDF_CONFLICT_TYPES = {
    "PDF_POLE_NOT_IN_KMZ",
    "KMZ_POLE_NOT_IN_PDF",
    "PDF_SPAN_TOPOLOGY_MISMATCH",
    "PDF_SPAN_LENGTH_MISMATCH",
}


def _distance_ft(a: PoleEntity, b: PoleEntity) -> float:
    radius_m = 6_371_000
    lat1, lat2 = math.radians(a.latitude), math.radians(b.latitude)
    dlat = lat2 - lat1
    dlon = math.radians(b.longitude - a.longitude)
    hav = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * radius_m * math.asin(math.sqrt(hav)) * 3.28084


def _nearest_entity(
    coordinate: list[float], entities: list[PoleEntity], *, max_distance_ft: float = 50
) -> PoleEntity | None:
    probe = PoleEntity(latitude=float(coordinate[1]), longitude=float(coordinate[0]))
    candidates = [
        (entity, _distance_ft(probe, entity))
        for entity in entities
        if entity.latitude is not None and entity.longitude is not None
    ]
    if not candidates:
        return None
    entity, distance = min(candidates, key=lambda item: item[1])
    return entity if distance <= max_distance_ft else None


def compare_pdf_to_kmz(db: Session, project_id: uuid.UUID, document_id: uuid.UUID) -> list[Conflict]:
    db.execute(delete(Conflict).where(
        Conflict.project_id == project_id,
        Conflict.source_document_id == document_id,
        Conflict.conflict_type.in_(PDF_CONFLICT_TYPES),
    ))
    entities = list(db.scalars(select(PoleEntity).where(PoleEntity.project_id == project_id)))
    entity_by_id = {item.id: item for item in entities}
    sources = list(db.scalars(select(PoleEntitySource).where(
        PoleEntitySource.pole_entity_id.in_([item.id for item in entities]),
        PoleEntitySource.source_document_id == document_id,
        PoleEntitySource.source_type == "PDF_EVIDENCE",
    ))) if entities else []
    entity_ids_in_pdf = {item.pole_entity_id for item in sources}
    evidence = list(db.scalars(select(PdfPoleEvidence).where(PdfPoleEvidence.document_id == document_id)))
    evidence_by_id = {item.id: item for item in evidence}
    pdf_pole_ids = {
        value for item in evidence for value in (item.pole_id, item.from_pole_id, item.to_pole_id) if value
    }
    assets = list(db.scalars(select(Asset).where(Asset.project_id == project_id)))
    conflicts: list[Conflict] = []

    for entity_id in entity_ids_in_pdf:
        entity = entity_by_id[entity_id]
        if entity.resolution_status not in {"UNRESOLVED", "AMBIGUOUS"}:
            continue
        source = next(item for item in sources if item.pole_entity_id == entity.id)
        item = evidence_by_id.get(source.source_id)
        conflict = Conflict(
            project_id=project_id,
            object_key=f"pdf-pole:{document_id}:{entity.canonical_pole_id or entity.canonical_eid}",
            conflict_type="PDF_POLE_NOT_IN_KMZ",
            severity="HIGH" if entity.resolution_status == "UNRESOLVED" else "MEDIUM",
            status="OPEN",
            summary=f"PDF pole {entity.canonical_pole_id or entity.canonical_eid} is not resolved to a KMZ asset.",
            details_json=json.dumps({"sources": [], "resolution_status": entity.resolution_status}),
            source_document_id=document_id,
            source_page=item.page_number if item else None,
            pole_entity_id=entity.id,
            evidence_json=json.dumps({"raw_text": item.raw_text if item else None}),
            expected_value="Matching KMZ pole asset",
            observed_value=entity.resolution_status,
            confidence=item.confidence if item else entity.confidence,
        )
        db.add(conflict)
        conflicts.append(conflict)

    for asset in assets:
        if asset.asset_type != "POLE":
            continue
        pole_ids, _ = asset_identifiers(asset)
        for pole_id in pole_ids - pdf_pole_ids:
            conflict = Conflict(
                project_id=project_id,
                object_key=f"kmz-pole:{document_id}:{asset.id}:{pole_id}",
                conflict_type="KMZ_POLE_NOT_IN_PDF",
                severity="MEDIUM",
                status="OPEN",
                summary=f"KMZ pole {pole_id} is absent from the selected PDF.",
                details_json=json.dumps({"sources": [], "pole_id": pole_id}),
                source_document_id=document_id,
                asset_id=asset.id,
                expected_value="Pole ID present in selected PDF",
                observed_value="Not present",
                confidence=0.99,
            )
            db.add(conflict)
            conflicts.append(conflict)

    relationships = list(db.scalars(select(PoleRelationship).where(
        PoleRelationship.project_id == project_id,
        PoleRelationship.source_document_id == document_id,
    )))
    coordinate_entities = [
        item for item in entities if item.latitude is not None and item.longitude is not None
    ]
    topology_pairs: set[frozenset[uuid.UUID]] = set()
    for asset in assets:
        if asset.asset_type != "AERIAL_SPAN" or not asset.geometry_json:
            continue
        try:
            coordinates = json.loads(asset.geometry_json)["coordinates"]
            from_entity = _nearest_entity(coordinates[0], coordinate_entities)
            to_entity = _nearest_entity(coordinates[-1], coordinate_entities)
            if from_entity and to_entity:
                topology_pairs.add(frozenset((from_entity.id, to_entity.id)))
        except (KeyError, TypeError, ValueError, IndexError):
            continue

    for relationship in relationships:
        from_entity = entity_by_id.get(relationship.from_pole_entity_id)
        to_entity = entity_by_id.get(relationship.to_pole_entity_id)
        if not from_entity or not to_entity:
            continue
        if topology_pairs and frozenset((from_entity.id, to_entity.id)) not in topology_pairs:
            conflict = Conflict(
                project_id=project_id,
                object_key=f"pdf-topology:{relationship.id}",
                conflict_type="PDF_SPAN_TOPOLOGY_MISMATCH",
                severity="HIGH",
                status="OPEN",
                summary=f"PDF span {relationship.from_external_pole_id} → {relationship.to_external_pole_id} differs from KMZ topology.",
                details_json=json.dumps({"sources": [], "relationship_id": str(relationship.id)}),
                source_document_id=document_id,
                source_page=relationship.source_page,
                pole_entity_id=from_entity.id,
                evidence_json=json.dumps({"raw_text": relationship.raw_text}),
                expected_value="Matching KMZ topology edge",
                observed_value="Edge not found",
                confidence=relationship.confidence,
            )
            db.add(conflict)
            conflicts.append(conflict)

        if relationship.designed_length_ft is None or None in (
            from_entity.latitude, from_entity.longitude, to_entity.latitude, to_entity.longitude
        ):
            continue
        calculated = _distance_ft(from_entity, to_entity)
        difference = abs(relationship.designed_length_ft - calculated)
        threshold = max(
            settings.pdf_span_length_min_difference_ft,
            relationship.designed_length_ft * settings.pdf_span_length_difference_ratio,
        )
        if difference > threshold:
            conflict = Conflict(
                project_id=project_id,
                object_key=f"pdf-length:{relationship.id}",
                conflict_type="PDF_SPAN_LENGTH_MISMATCH",
                severity="MEDIUM",
                status="OPEN",
                summary=f"PDF span length differs by {difference:.1f} ft from the KMZ-coordinate distance.",
                details_json=json.dumps({"sources": [], "relationship_id": str(relationship.id), "threshold_ft": threshold}),
                source_document_id=document_id,
                source_page=relationship.source_page,
                pole_entity_id=from_entity.id,
                evidence_json=json.dumps({"raw_text": relationship.raw_text}),
                expected_value=f"{relationship.designed_length_ft:.1f} ft designed",
                observed_value=f"{calculated:.1f} ft calculated",
                confidence=relationship.confidence,
            )
            db.add(conflict)
            conflicts.append(conflict)

    db.commit()
    for conflict in conflicts:
        db.refresh(conflict)
    return conflicts
