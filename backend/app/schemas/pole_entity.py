from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class PoleEntityRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    canonical_pole_id: str | None
    canonical_eid: str | None
    latitude: float | None
    longitude: float | None
    geometry_source: str | None
    resolution_status: str
    confidence: float
    created_at: datetime
    updated_at: datetime


class PoleEntitySourceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    pole_entity_id: uuid.UUID
    source_type: str
    source_id: uuid.UUID
    source_document_id: uuid.UUID | None
    external_pole_id: str | None
    external_eid: str | None
    match_method: str
    confidence: float
    created_at: datetime


class PoleEntityPage(BaseModel):
    items: list[PoleEntityRead]
    total: int
    offset: int
    limit: int


class PoleRelationshipRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    from_pole_entity_id: uuid.UUID | None
    to_pole_entity_id: uuid.UUID | None
    from_external_pole_id: str
    to_external_pole_id: str
    relationship_type: str
    designed_length_ft: float | None
    source_document_id: uuid.UUID
    source_evidence_id: uuid.UUID
    source_page: int
    raw_text: str
    confidence: float
    resolution_status: str
    derived_geojson: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime


class PoleRelationshipPage(BaseModel):
    items: list[PoleRelationshipRead]
    total: int
    offset: int
    limit: int


class ResolutionRequest(BaseModel):
    project_id: uuid.UUID
    dry_run: bool = True


class DocumentResolutionRequest(BaseModel):
    dry_run: bool = True


class ResolutionReport(BaseModel):
    project_id: str
    document_id: str | None
    dry_run: bool
    total_evidence: int
    resolved: int
    unresolved: int
    ambiguous: int
    manual: int
    created_entities: int
    reused_entities: int
    entities: list[dict[str, Any]]


class ManualMatchRequest(BaseModel):
    asset_id: uuid.UUID
    reason: str = Field(min_length=1, max_length=2000)
    reviewer: str = Field(min_length=1, max_length=255)


class UnmatchRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)
    reviewer: str = Field(min_length=1, max_length=255)


class CommitRequest(BaseModel):
    confirmed: Literal[True]
    reason: str = Field(min_length=1, max_length=2000)
    reviewer: str = Field(min_length=1, max_length=255)


class CommitReport(BaseModel):
    document_id: str
    project_id: str
    assets_created: int
    entity_resolution: ResolutionReport
    relationships: dict[str, int]
