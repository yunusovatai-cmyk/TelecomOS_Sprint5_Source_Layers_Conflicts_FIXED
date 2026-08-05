-- Additive migration for PDF Pole Extraction evidence.
-- Safe to apply after the existing projects/documents/assets schema is present.

CREATE TABLE IF NOT EXISTS pdf_page_texts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    page_number INTEGER NOT NULL,
    raw_text TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_pdf_page_texts_document_page UNIQUE (document_id, page_number)
);

CREATE INDEX IF NOT EXISTS ix_pdf_page_texts_document_id
    ON pdf_page_texts(document_id);

CREATE TABLE IF NOT EXISTS pdf_pole_evidence (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    page_number INTEGER NOT NULL,
    evidence_type VARCHAR(32) NOT NULL,
    pole_id VARCHAR(64),
    from_pole_id VARCHAR(64),
    to_pole_id VARCHAR(64),
    span_length_ft DOUBLE PRECISION,
    raw_text TEXT NOT NULL,
    bbox_json TEXT NOT NULL,
    confidence DOUBLE PRECISION NOT NULL,
    matched_asset_id UUID REFERENCES assets(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_pdf_pole_evidence_document_id ON pdf_pole_evidence(document_id);
CREATE INDEX IF NOT EXISTS ix_pdf_pole_evidence_page_number ON pdf_pole_evidence(page_number);
CREATE INDEX IF NOT EXISTS ix_pdf_pole_evidence_type ON pdf_pole_evidence(evidence_type);
CREATE INDEX IF NOT EXISTS ix_pdf_pole_evidence_pole_id ON pdf_pole_evidence(pole_id);
CREATE INDEX IF NOT EXISTS ix_pdf_pole_evidence_from_pole_id ON pdf_pole_evidence(from_pole_id);
CREATE INDEX IF NOT EXISTS ix_pdf_pole_evidence_to_pole_id ON pdf_pole_evidence(to_pole_id);
CREATE INDEX IF NOT EXISTS ix_pdf_pole_evidence_matched_asset_id ON pdf_pole_evidence(matched_asset_id);

ALTER TABLE pdf_pole_evidence ADD COLUMN IF NOT EXISTS external_eid VARCHAR(128);
ALTER TABLE pdf_pole_evidence ADD COLUMN IF NOT EXISTS review_status VARCHAR(32) NOT NULL DEFAULT 'OPEN';
CREATE INDEX IF NOT EXISTS ix_pdf_pole_evidence_external_eid ON pdf_pole_evidence(external_eid);
CREATE INDEX IF NOT EXISTS ix_pdf_pole_evidence_review_status ON pdf_pole_evidence(review_status);
ALTER TABLE pdf_page_texts ADD COLUMN IF NOT EXISTS page_width DOUBLE PRECISION NOT NULL DEFAULT 0;
ALTER TABLE pdf_page_texts ADD COLUMN IF NOT EXISTS page_height DOUBLE PRECISION NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS document_blobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL UNIQUE REFERENCES documents(id) ON DELETE CASCADE,
    content BYTEA NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS ix_document_blobs_document_id ON document_blobs(document_id);

CREATE TABLE IF NOT EXISTS pole_entities (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    canonical_pole_id VARCHAR(64),
    canonical_eid VARCHAR(128),
    latitude DOUBLE PRECISION,
    longitude DOUBLE PRECISION,
    geometry_source VARCHAR(64),
    resolution_status VARCHAR(32) NOT NULL DEFAULT 'UNRESOLVED',
    confidence DOUBLE PRECISION NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_pole_entities_project_pole_id UNIQUE (project_id, canonical_pole_id),
    CONSTRAINT uq_pole_entities_project_eid UNIQUE (project_id, canonical_eid)
);
CREATE INDEX IF NOT EXISTS ix_pole_entities_project_id ON pole_entities(project_id);
CREATE INDEX IF NOT EXISTS ix_pole_entities_canonical_pole_id ON pole_entities(canonical_pole_id);
CREATE INDEX IF NOT EXISTS ix_pole_entities_canonical_eid ON pole_entities(canonical_eid);
CREATE INDEX IF NOT EXISTS ix_pole_entities_resolution_status ON pole_entities(resolution_status);

CREATE TABLE IF NOT EXISTS pole_entity_sources (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pole_entity_id UUID NOT NULL REFERENCES pole_entities(id) ON DELETE CASCADE,
    source_type VARCHAR(32) NOT NULL,
    source_id UUID NOT NULL,
    source_document_id UUID REFERENCES documents(id) ON DELETE CASCADE,
    external_pole_id VARCHAR(64),
    external_eid VARCHAR(128),
    match_method VARCHAR(32) NOT NULL,
    confidence DOUBLE PRECISION NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_pole_entity_source UNIQUE (pole_entity_id, source_type, source_id)
);
CREATE INDEX IF NOT EXISTS ix_pole_entity_sources_pole_entity_id ON pole_entity_sources(pole_entity_id);
CREATE INDEX IF NOT EXISTS ix_pole_entity_sources_source_type ON pole_entity_sources(source_type);
CREATE INDEX IF NOT EXISTS ix_pole_entity_sources_source_id ON pole_entity_sources(source_id);
CREATE INDEX IF NOT EXISTS ix_pole_entity_sources_source_document_id ON pole_entity_sources(source_document_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_pole_entity_sources_asset
    ON pole_entity_sources(source_id) WHERE source_type = 'ASSET';

-- Earlier development copies used ON DELETE SET NULL here, which leaves a
-- polymorphic PDF_EVIDENCE source pointing at deleted evidence. Normalize the
-- constraint on every idempotent migration run.
ALTER TABLE pole_entity_sources
    DROP CONSTRAINT IF EXISTS pole_entity_sources_source_document_id_fkey;
ALTER TABLE pole_entity_sources
    ADD CONSTRAINT pole_entity_sources_source_document_id_fkey
    FOREIGN KEY (source_document_id) REFERENCES documents(id) ON DELETE CASCADE;

CREATE TABLE IF NOT EXISTS pole_entity_audits (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pole_entity_id UUID NOT NULL REFERENCES pole_entities(id) ON DELETE CASCADE,
    action VARCHAR(32) NOT NULL,
    reason TEXT NOT NULL,
    reviewer VARCHAR(255) NOT NULL,
    before_json TEXT NOT NULL,
    after_json TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_pole_entity_audits_pole_entity_id ON pole_entity_audits(pole_entity_id);
CREATE INDEX IF NOT EXISTS ix_pole_entity_audits_action ON pole_entity_audits(action);

CREATE TABLE IF NOT EXISTS pole_relationships (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    from_pole_entity_id UUID REFERENCES pole_entities(id) ON DELETE SET NULL,
    to_pole_entity_id UUID REFERENCES pole_entities(id) ON DELETE SET NULL,
    from_external_pole_id VARCHAR(64) NOT NULL,
    to_external_pole_id VARCHAR(64) NOT NULL,
    relationship_type VARCHAR(32) NOT NULL DEFAULT 'AERIAL_SPAN',
    designed_length_ft DOUBLE PRECISION,
    source_document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    source_evidence_id UUID NOT NULL UNIQUE REFERENCES pdf_pole_evidence(id) ON DELETE CASCADE,
    source_page INTEGER NOT NULL,
    raw_text TEXT NOT NULL,
    confidence DOUBLE PRECISION NOT NULL,
    resolution_status VARCHAR(32) NOT NULL DEFAULT 'UNRESOLVED',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_pole_relationships_project_id ON pole_relationships(project_id);
CREATE INDEX IF NOT EXISTS ix_pole_relationships_from_entity ON pole_relationships(from_pole_entity_id);
CREATE INDEX IF NOT EXISTS ix_pole_relationships_to_entity ON pole_relationships(to_pole_entity_id);
CREATE INDEX IF NOT EXISTS ix_pole_relationships_source_document_id ON pole_relationships(source_document_id);
CREATE INDEX IF NOT EXISTS ix_pole_relationships_source_evidence_id ON pole_relationships(source_evidence_id);
CREATE INDEX IF NOT EXISTS ix_pole_relationships_source_page ON pole_relationships(source_page);
CREATE INDEX IF NOT EXISTS ix_pole_relationships_status ON pole_relationships(resolution_status);
CREATE INDEX IF NOT EXISTS ix_pole_relationships_type ON pole_relationships(relationship_type);

ALTER TABLE conflicts ADD COLUMN IF NOT EXISTS source_document_id UUID REFERENCES documents(id) ON DELETE CASCADE;
ALTER TABLE conflicts ADD COLUMN IF NOT EXISTS source_page INTEGER;
ALTER TABLE conflicts ADD COLUMN IF NOT EXISTS pole_entity_id UUID REFERENCES pole_entities(id) ON DELETE SET NULL;
ALTER TABLE conflicts ADD COLUMN IF NOT EXISTS asset_id UUID REFERENCES assets(id) ON DELETE SET NULL;
ALTER TABLE conflicts ADD COLUMN IF NOT EXISTS evidence_json TEXT;
ALTER TABLE conflicts ADD COLUMN IF NOT EXISTS expected_value TEXT;
ALTER TABLE conflicts ADD COLUMN IF NOT EXISTS observed_value TEXT;
ALTER TABLE conflicts ADD COLUMN IF NOT EXISTS confidence DOUBLE PRECISION;
CREATE INDEX IF NOT EXISTS ix_conflicts_source_document_id ON conflicts(source_document_id);
CREATE INDEX IF NOT EXISTS ix_conflicts_source_page ON conflicts(source_page);
CREATE INDEX IF NOT EXISTS ix_conflicts_pole_entity_id ON conflicts(pole_entity_id);
CREATE INDEX IF NOT EXISTS ix_conflicts_asset_id ON conflicts(asset_id);
