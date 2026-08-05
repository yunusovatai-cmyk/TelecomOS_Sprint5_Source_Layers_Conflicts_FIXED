from __future__ import annotations

import uuid
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field


class ConflictRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    object_key: str
    conflict_type: str
    severity: str
    status: str
    summary: str
    details_json: str
    decision: str | None
    decision_reason: str | None
    created_at: datetime


class ConflictDecision(BaseModel):
    decision: str = Field(pattern="^(AERIAL|UG|NEEDS_REVIEW)$")
    decision_reason: str | None = Field(default=None, max_length=2000)
