-- Consolidate application access behind one non-owner PostgreSQL role.
--
-- Execute as the database/schema owner after migrations 001 through 003.  The
-- login itself (and its password) is provisioned separately so credentials do
-- not enter version control.  PostgreSQL has no GRANTable DROP privilege:
-- only an object owner (or a superuser) can drop an artifact.  Keep this role
-- non-owner and do not grant it membership in an owner role.

-- Manual Extraction of the application role from the legacy per-service roles.  This

-- CREATE ROLE rag_ingestion_application NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;

-- REVOKE ALL ON SCHEMA rag FROM rag_ingestion_application;
-- GRANT USAGE ON SCHEMA rag TO rag_ingestion_application;
-- GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA rag TO rag_ingestion_application;
-- GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA rag TO rag_ingestion_application;
-- GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA rag TO rag_ingestion_application;
-- GRANT USAGE ON ALL TYPES IN SCHEMA rag TO rag_ingestion_application;

-- ALTER ROLE rag_ingestion_application
--     WITH LOGIN
--     PASSWORD 'YourStrongPasswordHere';



DO $$ BEGIN
    CREATE ROLE rag_ingestion_application NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

REVOKE ALL ON SCHEMA rag FROM rag_ingestion_application;
GRANT USAGE ON SCHEMA rag TO rag_ingestion_application;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA rag TO rag_ingestion_application;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA rag TO rag_ingestion_application;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA rag TO rag_ingestion_application;
GRANT USAGE ON ALL TYPES IN SCHEMA rag TO rag_ingestion_application;

-- Apply the same non-ownership access model to artifacts introduced by later
-- migrations. Run this as the role that owns artifacts in schema rag.
ALTER DEFAULT PRIVILEGES IN SCHEMA rag
    GRANT ALL PRIVILEGES ON TABLES TO rag_ingestion_application;
ALTER DEFAULT PRIVILEGES IN SCHEMA rag
    GRANT ALL PRIVILEGES ON SEQUENCES TO rag_ingestion_application;
ALTER DEFAULT PRIVILEGES IN SCHEMA rag
    GRANT EXECUTE ON FUNCTIONS TO rag_ingestion_application;
ALTER DEFAULT PRIVILEGES IN SCHEMA rag
    GRANT USAGE ON TYPES TO rag_ingestion_application;

-- Retire the legacy, per-service group roles. Existing login identities are
-- disabled by the provisioning script, so only rag_application can connect.
REVOKE rag_ingestion_migrator FROM rag_ingestion_application;
REVOKE rag_ingestion_runtime FROM rag_ingestion_application;
REVOKE rag_ingestion_outbox_publisher FROM rag_ingestion_application;
REVOKE rag_ingestion_query_reader FROM rag_ingestion_application;
