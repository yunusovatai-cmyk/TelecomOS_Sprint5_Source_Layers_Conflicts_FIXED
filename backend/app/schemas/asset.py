from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class AssetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    asset_type: str
    name: str
    status: str
    longitude: float | None
    latitude: float | None
    geometry_type: str
    geometry_json: str | None
    issue: str | None
    source_document_id: uuid.UUID | None
    created_at: datetime


class AssetUpdate(BaseModel):
    status: str | None = Field(default=None, pattern="^(REVIEW|APPROVED|REJECTED|VERIFIED)$")
    issue: str | None = Field(default=None, max_length=255)
    name: str | None = Field(default=None, min_length=1, max_length=255)
