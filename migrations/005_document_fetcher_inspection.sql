-- Fetch-stage facts are separate from extraction results.  The upload API
-- records the client-declared mime_type, while the fetcher records what it
-- observes from the stored bytes.

ALTER TYPE rag.document_status ADD VALUE IF NOT EXISTS 'fetched' AFTER 'fetching';

ALTER TABLE rag.document_versions
    ADD COLUMN IF NOT EXISTS detected_mime_type TEXT,
    ADD COLUMN IF NOT EXISTS inspection_status TEXT NOT NULL DEFAULT 'pending'
        CHECK (inspection_status IN ('pending', 'valid', 'invalid', 'unsupported')),
    ADD COLUMN IF NOT EXISTS inspection_metadata JSONB NOT NULL DEFAULT '{}'::jsonb;

COMMENT ON COLUMN rag.document_versions.mime_type IS
    'MIME type declared by the submitting client; not trusted for parser selection.';
COMMENT ON COLUMN rag.document_versions.detected_mime_type IS
    'MIME type determined by the document-fetcher from source bytes.';
COMMENT ON COLUMN rag.document_versions.inspection_metadata IS
    'Safe fetch-stage evidence such as signature, PDF page count, and validation error codes.';
