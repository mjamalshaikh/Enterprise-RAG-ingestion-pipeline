# Work item: FastAPI document submission with transactional outbox

- Recorded at: 2026-07-25T18:49:53+05:00
- Status: completed

## Prompt

> Please create an Restful API using FASTAPI using which i can submit any document , later maybe we will develop agents which can find the documents and submit documents based by calling the API that you shall create , however currently , make a simple client using which i can call upload the file or guide me a way how to submit the document maybe via tools like postman or other similar tools . Please note that the API should notify the first worker by storing a DocumentSubmitted event in the transactional outbox.

## Outcome

Implemented a FastAPI document-submission interface at `POST /v1/documents`.
The endpoint accepts a multipart file upload and an `X-Tenant-Id` header,
stores the immutable source bytes in the configured S3-compatible MinIO source
bucket, then inserts the document metadata, initial version, and a
`DocumentSubmitted` outbox entry in one PostgreSQL transaction.

The outbox row targets `rag.ingestion.v1.document.submitted`, uses the existing
`ingestion-event` Avro envelope contract, and contains only the source object
URI and metadata; document bytes are never added to the event payload. This is
the handoff for the document-fetcher worker. Kafka publishing remains the
outbox publisher's responsibility and does not occur in the HTTP request.

## Delivered files

- `src/rag_ingestion/interfaces/api.py` — FastAPI application, health endpoint,
  multipart document endpoint, hashing, upload orchestration, and response
  contract.
- `src/rag_ingestion/infrastructure/document_submission.py` — MinIO/S3 adapter
  and tenant-scoped PostgreSQL repository that atomically writes the document,
  version, and outbox row.
- `src/rag_ingestion/domain/events/document_submitted.py` — builder for the
  Avro-compatible `DocumentSubmitted` event envelope.
- `scripts/submit_document.py` — command-line upload client.
- `Docs/document-submission-api.md` — API startup, tenant setup, client,
  cURL, Swagger UI, and Postman instructions.

## Operational behavior

- The API requires an existing tenant UUID and sets PostgreSQL's transaction-
  local `app.tenant_id` value, preserving the schema's row-level-security
  boundary.
- `source_external_id` is optional; if supplied, it is tenant-scoped and
  prevents duplicate document submissions with `409 Conflict`.
- Since object storage cannot participate in PostgreSQL's transaction, the API
  uploads the object before the database transaction and performs a best-effort
  object delete if the database write fails.
- Required runtime configuration includes a PostgreSQL runtime identity plus a
  least-privilege MinIO API identity capable of writing the source bucket.

## Validation

- Python compilation completed successfully for source, tests, and scripts.
- A direct `DocumentSubmitted` envelope contract check passed.
- `uv lock --check` and `git diff --check` passed.
- Full pytest and Ruff execution could not run because the pre-existing
  repository `.venv` points to an unavailable Python interpreter.
