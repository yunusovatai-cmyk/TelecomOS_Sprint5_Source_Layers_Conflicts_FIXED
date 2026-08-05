from __future__ import annotations

import json
import re
from collections import defaultdict
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.asset import Asset
from app.models.conflict import Conflict
from app.models.document import Document


def _normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def rebuild_conflicts(project_id: str, db: Session) -> list[Conflict]:
    db.execute(delete(Conflict).where(Conflict.project_id == project_id))

    assets = list(db.scalars(select(Asset).where(Asset.project_id == project_id)))
    documents = {
        str(document.id): document
        for document in db.scalars(select(Document).where(Document.project_id == project_id))
    }

    groups: dict[str, list[Asset]] = defaultdict(list)
    for asset in assets:
        groups[_normalize(asset.name)].append(asset)

    conflicts: list[Conflict] = []

print("\n===== GROUPS =====")
for k, g in groups.items():
    print(k, [a.asset_type for a in g], [a.name for a in g])
print("==================")    for object_key, group in groups.items():
        types = {asset.asset_type for asset in group}
        if "AERIAL_SPAN" in types and "UG_SEGMENT" in types:
            sources = []
            for asset in group:
                document = documents.get(str(asset.source_document_id))
                sources.append({
                    "asset_id": str(asset.id),
                    "asset_type": asset.asset_type,
                    "asset_name": asset.name,
                    "document_id": str(asset.source_document_id) if asset.source_document_id else None,
                    "document_name": document.filename if document else None,
                    "revision": document.revision if document else None,
                })

            conflict = Conflict(
                project_id=project_id,
                object_key=object_key,
                conflict_type="AERIAL_VS_UG",
                severity="CRITICAL",
                status="OPEN",
                summary=f"{group[0].name}: Aerial and Underground variants exist.",
                details_json=json.dumps({"sources": sources}),
            )
            db.add(conflict)
            conflicts.append(conflict)

    db.commit()
    for conflict in conflicts:
        db.refresh(conflict)
    return conflicts
