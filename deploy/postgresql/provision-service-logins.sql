-- Provision the single PostgreSQL application login for Enterprise RAG.
--
-- Run as a database administrator after migrations 001 through 004. Passwords
-- come from the deployment secret manager and must never be committed.
-- The resulting login is deliberately not an owner of the database, schema,
-- tables, sequences, routines, or types; it therefore cannot DROP them.
--
-- Required psql environment variable: POSTGRES_APPLICATION_PASSWORD
-- Example:
--   Get-Content deploy/postgresql/provision-service-logins.sql |
--     docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U rag -d rag_ingestion

\set ON_ERROR_STOP on
\getenv postgres_application_password POSTGRES_APPLICATION_PASSWORD

SELECT set_config('rag.provision.application_password', :'postgres_application_password', false);

DO $$
DECLARE
    application_password TEXT := current_setting('rag.provision.application_password', true);
    legacy_login TEXT;
BEGIN
    IF application_password IS NULL OR application_password = '' THEN
        RAISE EXCEPTION 'Missing POSTGRES_APPLICATION_PASSWORD';
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rag_application') THEN
        CREATE ROLE rag_application LOGIN;
    END IF;

    EXECUTE format(
        'ALTER ROLE rag_application LOGIN INHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION CONNECTION LIMIT 32 PASSWORD %L',
        application_password
    );
    GRANT rag_ingestion_application TO rag_application;

    -- Older deployments may still have dedicated service logins. Disable them
    -- and revoke their role memberships; do not drop identities automatically.
    FOREACH legacy_login IN ARRAY ARRAY[
        'rag_migration_login', 'rag_document_fetcher', 'rag_content_extractor',
        'rag_chunker', 'rag_embedder', 'rag_indexer', 'rag_outbox_publisher',
        'rag_query_api'
    ] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = legacy_login) THEN
            EXECUTE format('ALTER ROLE %I NOLOGIN', legacy_login);
            EXECUTE format('REVOKE rag_ingestion_migrator FROM %I', legacy_login);
            EXECUTE format('REVOKE rag_ingestion_runtime FROM %I', legacy_login);
            EXECUTE format('REVOKE rag_ingestion_outbox_publisher FROM %I', legacy_login);
            EXECUTE format('REVOKE rag_ingestion_query_reader FROM %I', legacy_login);
        END IF;
    END LOOP;
END $$;
