-- Least-privilege PostgreSQL group roles for the RAG pipeline.
-- Execute as the database administrator after 001_enterprise_rag_metadata.sql.
-- Login identities and passwords are created outside this repository by the
-- secret manager / database administrator, then granted one group role below.

DO $$ BEGIN
    CREATE ROLE rag_ingestion_migrator NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN
    CREATE ROLE rag_ingestion_runtime NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN
    CREATE ROLE rag_ingestion_outbox_publisher NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN
    CREATE ROLE rag_ingestion_query_reader NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

REVOKE ALL ON SCHEMA rag FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA rag FROM PUBLIC;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA rag FROM PUBLIC;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA rag FROM PUBLIC;

GRANT USAGE ON SCHEMA rag TO rag_ingestion_runtime, rag_ingestion_outbox_publisher, rag_ingestion_query_reader;

-- Runtime workers: document state, chunk metadata, ACLs, failures/audit, and
-- outbox insertion. Row-level security still applies to every statement.
GRANT SELECT, INSERT, UPDATE ON rag.documents, rag.document_versions, rag.document_acl,
    rag.chunks, rag.ingestion_failures, rag.audit_log, rag.ingestion_outbox
    TO rag_ingestion_runtime;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA rag TO rag_ingestion_runtime;

-- Retrieval/API service: read PostgreSQL lineage and caller-derived ACL context.
GRANT SELECT ON rag.documents, rag.document_versions, rag.document_acl, rag.chunks
    TO rag_ingestion_query_reader;

-- Migrations retain DDL authority. Grant this role to the controlled migration
-- identity only; do not grant it to runtime workers or interactive users.
GRANT ALL PRIVILEGES ON SCHEMA rag TO rag_ingestion_migrator;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA rag TO rag_ingestion_migrator;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA rag TO rag_ingestion_migrator;

-- A security-definer boundary lets the publisher claim events across tenants
-- without giving it broad table reads or the BYPASSRLS attribute.
CREATE OR REPLACE FUNCTION rag.claim_outbox_events(worker_name TEXT, batch_size INTEGER)
RETURNS SETOF rag.ingestion_outbox
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = rag, pg_temp
AS $$
BEGIN
    IF batch_size < 1 OR batch_size > 1_000 THEN
        RAISE EXCEPTION 'batch_size must be in the range 1..1000';
    END IF;

    RETURN QUERY
    WITH claimable AS (
        SELECT id
        FROM rag.ingestion_outbox
        WHERE status IN ('pending', 'failed') AND available_at <= clock_timestamp()
        ORDER BY available_at, created_at
        FOR UPDATE SKIP LOCKED
        LIMIT batch_size
    )
    UPDATE rag.ingestion_outbox AS outbox
    SET status = 'publishing', locked_at = clock_timestamp(), locked_by = worker_name,
        attempt_count = outbox.attempt_count + 1
    FROM claimable
    WHERE outbox.id = claimable.id
    RETURNING outbox.*;
END;
$$;

CREATE OR REPLACE FUNCTION rag.complete_outbox_event(
    outbox_id UUID,
    worker_name TEXT,
    succeeded BOOLEAN,
    error_message TEXT DEFAULT NULL,
    retry_at TIMESTAMPTZ DEFAULT NULL
)
RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = rag, pg_temp
AS $$
BEGIN
    UPDATE rag.ingestion_outbox
    SET status = CASE WHEN succeeded THEN 'published' ELSE 'failed' END,
        published_at = CASE WHEN succeeded THEN clock_timestamp() ELSE NULL END,
        available_at = COALESCE(retry_at, available_at),
        last_error = CASE WHEN succeeded THEN NULL ELSE error_message END,
        locked_at = NULL,
        locked_by = NULL
    WHERE id = outbox_id
      AND status = 'publishing'
      AND locked_by = worker_name;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'outbox event % is not claimed by worker %', outbox_id, worker_name;
    END IF;
END;
$$;

REVOKE ALL ON FUNCTION rag.claim_outbox_events(TEXT, INTEGER) FROM PUBLIC;
REVOKE ALL ON FUNCTION rag.complete_outbox_event(UUID, TEXT, BOOLEAN, TEXT, TIMESTAMPTZ) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION rag.claim_outbox_events(TEXT, INTEGER) TO rag_ingestion_outbox_publisher;
GRANT EXECUTE ON FUNCTION rag.complete_outbox_event(UUID, TEXT, BOOLEAN, TEXT, TIMESTAMPTZ) TO rag_ingestion_outbox_publisher;

-- Example identity binding (run outside version control with a secret value):
-- CREATE ROLE rag_worker_login LOGIN PASSWORD '<secret>' INHERIT;
-- GRANT rag_ingestion_runtime TO rag_worker_login;
-- The application must SET LOCAL app.tenant_id within each transaction before
-- accessing tenant-owned tables.
