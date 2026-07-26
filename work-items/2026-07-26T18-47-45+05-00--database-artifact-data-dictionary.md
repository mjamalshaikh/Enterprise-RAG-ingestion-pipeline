# Work item: Database and artifact data dictionary

- Recorded at: 2026-07-26T18:47:45+05:00
- Status: completed

## Prompt

> can you create a document which signifies the purpose of each field in the database tables and other artifacts like indexes , types ( enums ) , and roles , .. etc and at what stage it should be database each fields should be inserted , updated and example values of each field .

## Outcome

Created `Docs/database-artifact-data-dictionary.docx`, a field-level technical
reference for the PostgreSQL schema and related pipeline artifacts.

## Coverage

- All fields in the current `rag` PostgreSQL tables: tenants, documents,
  document versions, ACLs, chunks, outbox, processed events, failures, and
  audit log.
- The `tenant_status` and `document_status` enum values and their permitted
  lifecycle transitions.
- Insert/update timing for each field across Submit, Fetch, Extract, Chunk,
  Embed, Index, Outbox Publish, Failure/Recovery, and Delete stages.
- PostgreSQL uniqueness constraints, partial indexes, update triggers, and
  row-level-security policy behavior.
- Database group roles and the security-definer outbox claim/complete
  functions.
- Qdrant hybrid collection/vector and payload-index contract.
- Kafka Avro ingestion-event envelope fields and artifact-reference guidance.
- Citation/provenance mapping from a Qdrant result through chunk and document
  version records to the original or normalized source artifact.

## Key design note

The current relational schema supports document-version and chunk-level
provenance through hashes, object URIs, page ranges, and section paths. Exact
citations for tables, images, diagrams, DOM locations, or quote spans require
a normalized-artifact source-anchor contract or a future dedicated
`source_anchors` table containing unit IDs, bounding boxes/DOM paths, captions,
text spans, and artifact checksums.
