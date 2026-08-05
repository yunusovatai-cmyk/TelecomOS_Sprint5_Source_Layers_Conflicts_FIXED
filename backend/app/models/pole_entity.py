from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PoleEntity(Base):
    __tablename__ = "pole_entities"
    __table_args__ = (
        UniqueConstraint("project_id", "canonical_pole_id", name="uq_pole_entities_project_pole_id"),
        UniqueConstraint("project_id", "canonical_eid", name="uq_pole_entities_project_eid"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    canonical_pole_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    canonical_eid: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    geometry_source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    resolution_status: Mapped[str] = mapped_column(String(32), default="UNRESOLVED", index=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class PoleEntitySource(Base):
    __tablename__ = "pole_entity_sources"
    __table_args__ = (
        UniqueConstraint("pole_entity_id", "source_type", "source_id", name="uq_pole_entity_source"),
        Index(
            "uq_pole_entity_sources_asset",
            "source_id",
            unique=True,
            postgresql_where=text("source_type = 'ASSET'"),
            sqlite_where=text("source_type = 'ASSET'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    pole_entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pole_entities.id", ondelete="CASCADE"), index=True
    )
    source_type: Mapped[str] = mapped_column(String(32), index=True)
    source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    source_document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=True, index=True
    )
    external_pole_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    external_eid: Mapped[str | None] = mapped_column(String(128), nullable=True)
    match_method: Mapped[str] = mapped_column(String(32))
    confidence: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PoleEntityAudit(Base):
    __tablename__ = "pole_entity_audits"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    pole_entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pole_entities.id", ondelete="CASCADE"), index=True
    )
    action: Mapped[str] = mapped_column(String(32), index=True)
    reason: Mapped[str] = mapped_column(Text)
    reviewer: Mapped[str] = mapped_column(String(255))
    before_json: Mapped[str] = mapped_column(Text)
    after_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PoleRelationship(Base):
    __tablename__ = "pole_relationships"
    __table_args__ = (UniqueConstraint("source_evidence_id", name="uq_pole_relationship_source_evidence"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    from_pole_entity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pole_entities.id", ondelete="SET NULL"), nullable=True, index=True
    )
    to_pole_entity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pole_entities.id", ondelete="SET NULL"), nullable=True, index=True
    )
    from_external_pole_id: Mapped[str] = mapped_column(String(64), index=True)
    to_external_pole_id: Mapped[str] = mapped_column(String(64), index=True)
    relationship_type: Mapped[str] = mapped_column(String(32), default="AERIAL_SPAN", index=True)
    designed_length_ft: Mapped[float | None] = mapped_column(Float, nullable=True)
    source_document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    source_evidence_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pdf_pole_evidence.id", ondelete="CASCADE"), index=True
    )
    source_page: Mapped[int] = mapped_column(Integer, index=True)
    raw_text: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float)
    resolution_status: Mapped[str] = mapped_column(String(32), default="UNRESOLVED", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
