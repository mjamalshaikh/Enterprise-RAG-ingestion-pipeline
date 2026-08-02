-- Content-extractor evidence is persisted separately from source inspection.
-- This migration is additive so an existing deployment can reprocess versions safely.

ALTER TYPE rag.document_status ADD VALUE IF NOT EXISTS 'extracted' AFTER 'extracting';

ALTER TABLE rag.document_versions
    ADD COLUMN IF NOT EXISTS extraction_status TEXT NOT NULL DEFAULT 'pending'
        CHECK (extraction_status IN ('pending', 'succeeded', 'partial', 'needs_review', 'failed')),
    ADD COLUMN IF NOT EXISTS extraction_manifest_uri TEXT;

COMMENT ON COLUMN rag.document_versions.normalized_object_uri IS
    'Tenant-scoped immutable normalized content artifact. It may contain extracted text and figure evidence.';
COMMENT ON COLUMN rag.document_versions.extraction_manifest_uri IS
    'Tenant-scoped immutable extraction manifest with parser lineage and safe quality metrics.';
