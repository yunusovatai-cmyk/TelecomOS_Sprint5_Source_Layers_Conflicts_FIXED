from __future__ import annotations
import uuid
from datetime import datetime
from pydantic import BaseModel, ConfigDict

class DocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    project_id: uuid.UUID
    filename: str
    document_type: str
    revision: str | None
    sha256: str
    mime_type: str | None
    size_bytes: int
    processing_status: str
    created_at: datetime
