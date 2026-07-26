# Work item: FastAPI runtime debugging and MinIO access

- Recorded at: 2026-07-26T18:41:29+05:00
- Status: completed

## Prompt

> i am getting below error , please guide how to fix it . also guide how to run the application in debug mode as i would like to debug the fastAPI application .

## Outcome

Reviewed the document-submission API startup and upload failures and added the
missing runtime support for local debugging and MinIO authorization diagnosis.
The initial upload response intentionally masks storage details with HTTP 503;
the API now records the underlying MinIO/S3 exception in its process log without
logging credentials.

The investigation established these distinct failure modes:

- A missing MinIO bucket or unreachable endpoint produces a connection or
  `NoSuchBucket` error.
- `403` from `HeadBucket` indicates an authorization or credential issue.
- `SignatureDoesNotMatch` from `PutObject` confirms that the configured secret
  does not match the selected MinIO access key.

## Delivered changes

- `src/rag_ingestion/interfaces/api.py` logs the source-storage exception and
  traceback locally before returning the safe HTTP 503 response.
- `src/rag_ingestion/infrastructure/document_submission.py` selects the MinIO
  API access key and secret as an all-or-nothing pair. If a complete API pair is
  not configured, it consistently falls back to the ingestion access-key/secret
  pair. This prevents signing requests with an access key from one identity and
  a secret from another.
- `deploy/minio/rag-api-upload-policy.json` provides a least-privilege policy
  for source-bucket discovery, upload, multipart support, and cleanup.
- `Docs/document-submission-api.md` documents MinIO preflight checks, 403 and
  signature troubleshooting, policy attachment, and VS Code debug startup.
- `.vscode/launch.json` was updated locally with fault-handler options to aid
  diagnosis of debugger native-process failures.

## Operational guidance

- The selected local storage identity is `ingestion-service`; its configured
  `RAG_MINIO_SECRET_KEY` must exactly match the current MinIO secret for that
  access key.
- A policy containing `s3:ListBucket` on `arn:aws:s3:::rag-source` should allow
  `HeadBucket`. If it remains forbidden, verify the policy attachment and the
  active access-key/secret pair rather than changing the FastAPI endpoint.
- Use Python 3.13 for local VS Code debugging when the Python 3.14/debugpy
  combination exits with `Aborted!` before Uvicorn starts. Do not use
  `--reload` for breakpoint debugging because it spawns a child process.
- The submission API requires a PostgreSQL login with the
  `rag_ingestion_runtime` group role. A dedicated API login is preferable to
  reusing a worker login.

## Validation

- Source compilation and `git diff --check` passed after the credential-pair
  selection fix.
- The remaining MinIO `SignatureDoesNotMatch` response is external runtime
  configuration: update the ignored local secret to match the MinIO user, then
  restart the API debug process and rerun the documented preflight check.
