-- Additive, idempotent migration for private PDF object storage and background jobs.
-- BYTEA rows are intentionally retained. Run scripts/migrate_pdf_blobs.py first,
-- verify its report, then use its explicit --clear-bytea option if desired.

ALTER TABLE documents ADD COLUMN IF NOT EXISTS storage_bucket VARCHAR(128);
ALTER TABLE documents ADD COLUMN IF NOT EXISTS storage_object_key VARCHAR(512);
ALTER TABLE documents ADD COLUMN IF NOT EXISTS storage_size_bytes BIGINT;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS storage_mime_type VARCHAR(128);
CREATE UNIQUE INDEX IF NOT EXISTS uq_documents_project_sha256 ON documents(project_id, sha256);
CREATE UNIQUE INDEX IF NOT EXISTS uq_documents_storage_object
    ON documents(storage_bucket, storage_object_key)
    WHERE storage_object_key IS NOT NULL;

CREATE TABLE IF NOT EXISTS pdf_processing_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    operation VARCHAR(64) NOT NULL DEFAULT 'FULL_PIPELINE',
    idempotency_key VARCHAR(255) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'QUEUED',
    progress INTEGER NOT NULL DEFAULT 0 CHECK (progress BETWEEN 0 AND 100),
    stage VARCHAR(64) NOT NULL DEFAULT 'QUEUED',
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    max_attempts INTEGER NOT NULL DEFAULT 3 CHECK (max_attempts > 0),
    cancel_requested BOOLEAN NOT NULL DEFAULT FALSE,
    error_code VARCHAR(64),
    error_message VARCHAR(512),
    queued_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at TIMESTAMPTZ,
    heartbeat_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_pdf_processing_jobs_idempotency UNIQUE (idempotency_key)
);
CREATE INDEX IF NOT EXISTS ix_pdf_processing_jobs_project_id ON pdf_processing_jobs(project_id);
CREATE INDEX IF NOT EXISTS ix_pdf_processing_jobs_document_id ON pdf_processing_jobs(document_id);
CREATE INDEX IF NOT EXISTS ix_pdf_processing_jobs_status ON pdf_processing_jobs(status);
CREATE INDEX IF NOT EXISTS ix_pdf_processing_jobs_heartbeat_at ON pdf_processing_jobs(heartbeat_at);
CREATE INDEX IF NOT EXISTS ix_pdf_processing_jobs_project_created
    ON pdf_processing_jobs(project_id, created_at DESC);

CREATE TABLE IF NOT EXISTS pdf_rendered_pages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    page_number INTEGER NOT NULL CHECK (page_number > 0),
    bucket VARCHAR(128) NOT NULL,
    object_key VARCHAR(512) NOT NULL,
    size_bytes BIGINT NOT NULL CHECK (size_bytes > 0),
    sha256 VARCHAR(64) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_pdf_rendered_page UNIQUE (document_id, page_number)
);
CREATE INDEX IF NOT EXISTS ix_pdf_rendered_pages_document_id ON pdf_rendered_pages(document_id);
CREATE INDEX IF NOT EXISTS ix_pdf_rendered_pages_created_at ON pdf_rendered_pages(created_at);
CREATE UNIQUE INDEX IF NOT EXISTS uq_pdf_rendered_pages_object ON pdf_rendered_pages(bucket, object_key);
