-- Enterprise RAG metadata schema for PostgreSQL 16+.
-- Apply with a migration runner. Do not alter an applied migration in place.

CREATE DATABASE rag_ingestion
    WITH
    OWNER = keycloak_db_user
    ENCODING = 'UTF8'
    LC_COLLATE = 'en_US.utf8'
    LC_CTYPE = 'en_US.utf8'
    LOCALE_PROVIDER = 'libc'
    TABLESPACE = pg_default
    CONNECTION LIMIT = -1
    IS_TEMPLATE = False;

CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE SCHEMA IF NOT EXISTS rag;

DO $$ BEGIN
    CREATE TYPE rag.tenant_status AS ENUM ('active', 'suspended', 'deleted');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE rag.document_status AS ENUM (
        'submitted', 'fetching', 'extracting', 'chunking', 'embedding',
        'indexing', 'ready', 'failed', 'deleted'
    );
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

CREATE OR REPLACE FUNCTION rag.set_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN NEW.updated_at = clock_timestamp(); RETURN NEW; END; $$;

CREATE TABLE IF NOT EXISTS rag.tenants (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    slug TEXT NOT NULL UNIQUE CHECK (slug ~ '^[a-z0-9][a-z0-9-]{1,62}$'),
    display_name TEXT NOT NULL,
    status rag.tenant_status NOT NULL DEFAULT 'active',
    data_residency TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE IF NOT EXISTS rag.documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES rag.tenants(id),
    source_system TEXT NOT NULL,
    source_external_id TEXT NOT NULL,
    title TEXT,
    classification TEXT NOT NULL DEFAULT 'internal',
    status rag.document_status NOT NULL DEFAULT 'submitted',
    current_version_id UUID,
    discovered_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    deleted_at TIMESTAMPTZ,
    UNIQUE (tenant_id, source_system, source_external_id),
    UNIQUE (tenant_id, id)
);

CREATE TABLE IF NOT EXISTS rag.document_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES rag.tenants(id),
    document_id UUID NOT NULL,
    version_number INTEGER NOT NULL CHECK (version_number > 0),
    content_sha256 CHAR(64) NOT NULL CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
    source_object_uri TEXT NOT NULL,
    normalized_object_uri TEXT,
    mime_type TEXT NOT NULL,
    byte_size BIGINT NOT NULL CHECK (byte_size >= 0),
    language_code TEXT,
    extraction_config JSONB NOT NULL DEFAULT '{}'::jsonb,
    extraction_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    model_versions JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    deleted_at TIMESTAMPTZ,
    FOREIGN KEY (tenant_id, document_id) REFERENCES rag.documents(tenant_id, id),
    UNIQUE (tenant_id, document_id, version_number),
    UNIQUE (tenant_id, content_sha256),
    UNIQUE (tenant_id, id)
);

DO $$ BEGIN
    ALTER TABLE rag.documents ADD CONSTRAINT documents_current_version_fk
        FOREIGN KEY (tenant_id, current_version_id) REFERENCES rag.document_versions(tenant_id, id);
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

CREATE TABLE IF NOT EXISTS rag.document_acl (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES rag.tenants(id),
    document_id UUID NOT NULL,
    principal_type TEXT NOT NULL CHECK (principal_type IN ('user', 'group', 'role')),
    principal_id TEXT NOT NULL,
    permission TEXT NOT NULL CHECK (permission IN ('read', 'manage')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    FOREIGN KEY (tenant_id, document_id) REFERENCES rag.documents(tenant_id, id),
    UNIQUE (tenant_id, document_id, principal_type, principal_id, permission)
);

CREATE TABLE IF NOT EXISTS rag.chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES rag.tenants(id),
    document_version_id UUID NOT NULL,
    chunk_index INTEGER NOT NULL CHECK (chunk_index >= 0),
    qdrant_point_id UUID NOT NULL UNIQUE,
    content_sha256 CHAR(64) NOT NULL CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
    page_from INTEGER CHECK (page_from > 0),
    page_to INTEGER CHECK (page_to >= page_from),
    section_path TEXT[] NOT NULL DEFAULT '{}',
    token_count INTEGER NOT NULL CHECK (token_count > 0),
    character_count INTEGER NOT NULL CHECK (character_count > 0),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    embedding_model TEXT NOT NULL,
    embedding_model_version TEXT NOT NULL,
    chunking_strategy TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    deleted_at TIMESTAMPTZ,
    FOREIGN KEY (tenant_id, document_version_id) REFERENCES rag.document_versions(tenant_id, id),
    UNIQUE (tenant_id, document_version_id, chunk_index)
);

CREATE TABLE IF NOT EXISTS rag.ingestion_outbox (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES rag.tenants(id),
    event_id UUID NOT NULL DEFAULT gen_random_uuid(),
    aggregate_type TEXT NOT NULL,
    aggregate_id UUID NOT NULL,
    event_type TEXT NOT NULL,
    kafka_topic TEXT NOT NULL,
    schema_group_id TEXT NOT NULL DEFAULT 'rag.ingestion.v1',
    schema_artifact_id TEXT NOT NULL,
    payload JSONB NOT NULL,
    headers JSONB NOT NULL DEFAULT '{}'::jsonb,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'publishing', 'published', 'failed')),
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    available_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    locked_at TIMESTAMPTZ,
    locked_by TEXT,
    published_at TIMESTAMPTZ,
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (tenant_id, event_id)
);

CREATE TABLE IF NOT EXISTS rag.processed_events (
    tenant_id UUID NOT NULL REFERENCES rag.tenants(id),
    event_id UUID NOT NULL,
    consumer_name TEXT NOT NULL,
    processed_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    result JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (tenant_id, event_id, consumer_name)
);

CREATE TABLE IF NOT EXISTS rag.ingestion_failures (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES rag.tenants(id),
    document_version_id UUID,
    event_id UUID,
    stage TEXT NOT NULL,
    error_class TEXT NOT NULL,
    error_code TEXT,
    error_detail JSONB NOT NULL DEFAULT '{}'::jsonb,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    occurrence_count INTEGER NOT NULL DEFAULT 1 CHECK (occurrence_count > 0),
    resolved_at TIMESTAMPTZ,
    FOREIGN KEY (tenant_id, document_version_id) REFERENCES rag.document_versions(tenant_id, id)
);

CREATE TABLE IF NOT EXISTS rag.audit_log (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES rag.tenants(id),
    actor_type TEXT NOT NULL CHECK (actor_type IN ('user', 'service', 'system')),
    actor_id TEXT NOT NULL,
    action TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id UUID,
    correlation_id UUID,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

    CREATE INDEX IF NOT EXISTS documents_tenant_status_idx ON rag.documents (tenant_id, status) WHERE deleted_at IS NULL;
    CREATE INDEX IF NOT EXISTS document_versions_active_idx ON rag.document_versions (tenant_id, document_id, version_number DESC) WHERE deleted_at IS NULL;
    CREATE INDEX IF NOT EXISTS chunks_active_version_idx ON rag.chunks (tenant_id, document_version_id, chunk_index) WHERE is_active AND deleted_at IS NULL;
    CREATE INDEX IF NOT EXISTS document_acl_lookup_idx ON rag.document_acl (tenant_id, principal_type, principal_id, document_id);
    CREATE INDEX IF NOT EXISTS outbox_publishable_idx ON rag.ingestion_outbox (available_at, created_at) WHERE status IN ('pending', 'failed');
    CREATE INDEX IF NOT EXISTS failures_unresolved_idx ON rag.ingestion_failures (tenant_id, stage, last_seen_at DESC) WHERE resolved_at IS NULL;
    CREATE INDEX IF NOT EXISTS audit_log_tenant_time_idx ON rag.audit_log (tenant_id, occurred_at DESC);

DROP TRIGGER IF EXISTS tenants_set_updated_at ON rag.tenants;
CREATE TRIGGER tenants_set_updated_at BEFORE UPDATE ON rag.tenants FOR EACH ROW EXECUTE FUNCTION rag.set_updated_at();
DROP TRIGGER IF EXISTS documents_set_updated_at ON rag.documents;
CREATE TRIGGER documents_set_updated_at BEFORE UPDATE ON rag.documents FOR EACH ROW EXECUTE FUNCTION rag.set_updated_at();
DROP TRIGGER IF EXISTS document_versions_set_updated_at ON rag.document_versions;
CREATE TRIGGER document_versions_set_updated_at BEFORE UPDATE ON rag.document_versions FOR EACH ROW EXECUTE FUNCTION rag.set_updated_at();

-- The runtime role must issue SET LOCAL app.tenant_id = '<uuid>' per transaction.
-- Do not use the migration owner role as the runtime role; owners can bypass RLS.
ALTER TABLE rag.documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE rag.document_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE rag.document_acl ENABLE ROW LEVEL SECURITY;
ALTER TABLE rag.chunks ENABLE ROW LEVEL SECURITY;
ALTER TABLE rag.ingestion_outbox ENABLE ROW LEVEL SECURITY;
ALTER TABLE rag.processed_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE rag.ingestion_failures ENABLE ROW LEVEL SECURITY;
ALTER TABLE rag.audit_log ENABLE ROW LEVEL SECURITY;

DO $$
DECLARE table_name TEXT;
BEGIN
    FOREACH table_name IN ARRAY ARRAY['documents', 'document_versions', 'document_acl', 'chunks', 'ingestion_outbox', 'processed_events', 'ingestion_failures', 'audit_log']
    LOOP
        EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON rag.%I', table_name);
        EXECUTE format('CREATE POLICY tenant_isolation ON rag.%I USING (tenant_id = current_setting(''app.tenant_id'', true)::uuid) WITH CHECK (tenant_id = current_setting(''app.tenant_id'', true)::uuid)', table_name);
    END LOOP;
END $$;
