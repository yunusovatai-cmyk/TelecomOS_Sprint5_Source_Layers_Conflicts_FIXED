from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ProjectCreate(BaseModel):
    project_code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=255)


class ProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_code: str
    name: str
    status: str
    created_at: datetime
