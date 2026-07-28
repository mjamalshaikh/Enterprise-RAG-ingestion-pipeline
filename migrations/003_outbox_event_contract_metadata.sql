-- Replace registry-specific outbox metadata with local Avro contract names.
-- Apply after 001 and 002; do not edit those already-applied migrations.

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'rag' AND table_name = 'ingestion_outbox'
          AND column_name = 'schema_group_id'
    ) THEN
        ALTER TABLE rag.ingestion_outbox
            RENAME COLUMN schema_group_id TO event_contract_namespace;
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'rag' AND table_name = 'ingestion_outbox'
          AND column_name = 'schema_artifact_id'
    ) THEN
        ALTER TABLE rag.ingestion_outbox
            RENAME COLUMN schema_artifact_id TO event_schema_name;
    END IF;
END $$;
