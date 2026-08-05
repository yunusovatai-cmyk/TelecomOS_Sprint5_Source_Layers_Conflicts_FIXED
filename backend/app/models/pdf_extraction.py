from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import LargeBinary, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PdfPageText(Base):
    __tablename__ = "pdf_page_texts"
    __table_args__ = (UniqueConstraint("document_id", "page_number"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    page_number: Mapped[int] = mapped_column(Integer)
    raw_text: Mapped[str] = mapped_column(Text)
    page_width: Mapped[float] = mapped_column(Float, default=0.0)
    page_height: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DocumentBlob(Base):
    __tablename__ = "document_blobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), unique=True, index=True
    )
    content: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PdfPoleEvidence(Base):
    __tablename__ = "pdf_pole_evidence"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    page_number: Mapped[int] = mapped_column(Integer, index=True)
    evidence_type: Mapped[str] = mapped_column(String(32), index=True)
    pole_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    external_eid: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    from_pole_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    to_pole_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    span_length_ft: Mapped[float | None] = mapped_column(Float, nullable=True)
    raw_text: Mapped[str] = mapped_column(Text)
    bbox_json: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float)
    review_status: Mapped[str] = mapped_column(String(32), default="OPEN", index=True)
    matched_asset_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("assets.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
