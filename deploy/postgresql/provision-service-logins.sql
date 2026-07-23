-- Provision the PostgreSQL service identities for Enterprise RAG.
--
-- Run as a database administrator against the rag_ingestion database *after*
-- migrations/001_enterprise_rag_metadata.sql and
-- migrations/002_database_roles_and_privileges.sql.  This is deliberately not
-- a schema migration: passwords come from the deployment secret manager and
-- must never be recorded in a migration file or in Git.
--
-- Required psql environment variables:
--   POSTGRES_MIGRATOR_PASSWORD, POSTGRES_DOCUMENT_FETCHER_PASSWORD,
--   POSTGRES_CONTENT_EXTRACTOR_PASSWORD, POSTGRES_CHUNKER_PASSWORD,
--   POSTGRES_EMBEDDER_PASSWORD, POSTGRES_INDEXER_PASSWORD,
--   POSTGRES_OUTBOX_PUBLISHER_PASSWORD, POSTGRES_QUERY_API_PASSWORD
--
-- Example (PowerShell):
--   Get-Content deploy/postgresql/provision-service-logins.sql |
--     docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U rag -d rag_ingestion

\set ON_ERROR_STOP on
\getenv postgres_migrator_password POSTGRES_MIGRATOR_PASSWORD
\getenv postgres_document_fetcher_password POSTGRES_DOCUMENT_FETCHER_PASSWORD
\getenv postgres_content_extractor_password POSTGRES_CONTENT_EXTRACTOR_PASSWORD
\getenv postgres_chunker_password POSTGRES_CHUNKER_PASSWORD
\getenv postgres_embedder_password POSTGRES_EMBEDDER_PASSWORD
\getenv postgres_indexer_password POSTGRES_INDEXER_PASSWORD
\getenv postgres_outbox_publisher_password POSTGRES_OUTBOX_PUBLISHER_PASSWORD
\getenv postgres_query_api_password POSTGRES_QUERY_API_PASSWORD

-- Assign the psql values before entering the dollar-quoted PL/pgSQL body;
-- psql intentionally does not interpolate variables inside quoted SQL text.
SELECT set_config('rag.provision.migrator_password', :'postgres_migrator_password', false);
SELECT set_config('rag.provision.document_fetcher_password', :'postgres_document_fetcher_password', false);
SELECT set_config('rag.provision.content_extractor_password', :'postgres_content_extractor_password', false);
SELECT set_config('rag.provision.chunker_password', :'postgres_chunker_password', false);
SELECT set_config('rag.provision.embedder_password', :'postgres_embedder_password', false);
SELECT set_config('rag.provision.indexer_password', :'postgres_indexer_password', false);
SELECT set_config('rag.provision.outbox_publisher_password', :'postgres_outbox_publisher_password', false);
SELECT set_config('rag.provision.query_api_password', :'postgres_query_api_password', false);

DO $$
DECLARE
    service_roles CONSTANT jsonb := jsonb_build_array(
        jsonb_build_object('login', 'rag_migration_login', 'group_role', 'rag_ingestion_migrator', 'password', current_setting('rag.provision.migrator_password', true), 'limit', 2),
        jsonb_build_object('login', 'rag_document_fetcher', 'group_role', 'rag_ingestion_runtime', 'password', current_setting('rag.provision.document_fetcher_password', true), 'limit', 4),
        jsonb_build_object('login', 'rag_content_extractor', 'group_role', 'rag_ingestion_runtime', 'password', current_setting('rag.provision.content_extractor_password', true), 'limit', 4),
        jsonb_build_object('login', 'rag_chunker', 'group_role', 'rag_ingestion_runtime', 'password', current_setting('rag.provision.chunker_password', true), 'limit', 4),
        jsonb_build_object('login', 'rag_embedder', 'group_role', 'rag_ingestion_runtime', 'password', current_setting('rag.provision.embedder_password', true), 'limit', 4),
        jsonb_build_object('login', 'rag_indexer', 'group_role', 'rag_ingestion_runtime', 'password', current_setting('rag.provision.indexer_password', true), 'limit', 4),
        jsonb_build_object('login', 'rag_outbox_publisher', 'group_role', 'rag_ingestion_outbox_publisher', 'password', current_setting('rag.provision.outbox_publisher_password', true), 'limit', 2),
        jsonb_build_object('login', 'rag_query_api', 'group_role', 'rag_ingestion_query_reader', 'password', current_setting('rag.provision.query_api_password', true), 'limit', 8)
    );
    service_role jsonb;
BEGIN
    FOR service_role IN SELECT * FROM jsonb_array_elements(service_roles)
    LOOP
        IF service_role->>'password' IS NULL OR service_role->>'password' = '' THEN
            RAISE EXCEPTION 'Missing password for %', service_role->>'login';
        END IF;

        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = service_role->>'login') THEN
            EXECUTE format(
                'CREATE ROLE %I LOGIN INHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION CONNECTION LIMIT %s PASSWORD %L',
                service_role->>'login', (service_role->>'limit')::integer, service_role->>'password'
            );
        ELSE
            EXECUTE format(
                'ALTER ROLE %I LOGIN INHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION CONNECTION LIMIT %s PASSWORD %L',
                service_role->>'login', (service_role->>'limit')::integer, service_role->>'password'
            );
        END IF;
        EXECUTE format('GRANT %I TO %I', service_role->>'group_role', service_role->>'login');
    END LOOP;
END $$;
