# Document submission API

`POST /v1/documents` accepts an uploaded document, stores its original bytes in
the configured MinIO source bucket, and creates the document, version, and
`DocumentSubmitted` transactional-outbox record in one PostgreSQL transaction.
The outbox publisher will subsequently deliver the event to
`rag.ingestion.v1.document.submitted`, which is the input of the document
fetcher worker.

## Prerequisites

Start the local platform and apply the schema migrations. Create the tenant
first; the API deliberately requires its UUID in `X-Tenant-Id` so every write
is constrained by the PostgreSQL row-level-security tenant setting.

For a local test tenant, run this as the migration/admin database identity and
use the returned `id` in the request header:

```sql
INSERT INTO rag.tenants (slug, display_name)
VALUES ('demo', 'Demo tenant')
RETURNING id;
```

The API process needs a PostgreSQL identity with `rag_ingestion_runtime`
permissions and an object-storage identity allowed to write `rag-source`. The
existing local secret template supports that using `RAG_POSTGRES_DSN`,
`RAG_MINIO_API_ACCESS_KEY`, and `RAG_MINIO_API_SECRET_KEY` (or the fallback
`RAG_MINIO_ACCESS_KEY` / `RAG_MINIO_SECRET_KEY`). Do not use the MinIO root
credentials for the API.

Run the API from the repository root:

```powershell
uv run uvicorn rag_ingestion.interfaces.api:app --host 127.0.0.1 --port 8000 --reload
```

Swagger UI is then available at `http://127.0.0.1:8000/docs`.

## Submit a document

Using the included client:

```powershell
uv run python scripts/submit_document.py .\example.pdf --tenant-id "<tenant-uuid>"
```

Using cURL:

```powershell
curl.exe -X POST "http://127.0.0.1:8000/v1/documents" `
  -H "X-Tenant-Id: <tenant-uuid>" `
  -F "file=@C:\path\to\example.pdf" `
  -F "classification=internal" `
  -F "title=Example document" `
  -F "source_external_id=my-source-system-id-123"
```

In Postman, create a `POST` request to `/v1/documents`, add header
`X-Tenant-Id` with the existing tenant UUID, choose **Body → form-data**, then
add a `file` key of type **File**. The optional text keys are `title`,
`classification` (defaults to `internal`), and `source_external_id`.

`source_external_id` makes retries safe at the document level: a repeated
value for the same tenant returns `409 Conflict` instead of emitting a second
event. If omitted, the API generates one.

## Troubleshoot source-storage errors

If the endpoint returns `503` with `Source object storage is unavailable`,
read the API terminal output. It logs the original MinIO/S3 exception and a
traceback without including credentials. Check the source bucket and API
identity before retrying:

```powershell
uv run python -c "from rag_ingestion.config.settings import get_settings; from rag_ingestion.infrastructure.document_submission import SourceObjectStore; s = get_settings(); SourceObjectStore(s).client.head_bucket(Bucket=s.minio_source_bucket); print('MinIO bucket access passed:', s.minio_source_bucket)"
```

Interpret the result as follows:

| Error | Resolution |
| --- | --- |
| `EndpointConnectionError` / connection refused | Start MinIO and confirm `RAG_MINIO_ENDPOINT=localhost:9000` and `RAG_MINIO_SECURE=false` for host execution. |
| `NoCredentialsError` | Populate the ignored `secrets/local-runtime-secrets.env` file with the API service access key and secret key. |
| `403 AccessDenied` | In the MinIO console, grant the API identity read/write access to the `rag-source` bucket. |
| `404 NoSuchBucket` | Create the `rag-source` bucket in the MinIO console, then retry. |

Open the local MinIO console at `http://localhost:9001`, sign in with the
local administrator account, create `rag-source` if needed, and create or
update the API service user. The API reads `RAG_MINIO_API_ACCESS_KEY` and
`RAG_MINIO_API_SECRET_KEY` only when **both** are set; otherwise it uses the
`RAG_MINIO_ACCESS_KEY` / `RAG_MINIO_SECRET_KEY` pair. Do not configure only one
of the `RAG_MINIO_API_*` settings, as that would be an incomplete API identity.
Do not put administrator credentials in the API configuration.

### Fix `403 Forbidden` for the API identity

`403` from `HeadBucket` confirms that MinIO is running but the access key used
by the API has no suitable policy on `rag-source`. Attach the included
least-privilege policy at `deploy/minio/rag-api-upload-policy.json` to the
identity named by `RAG_MINIO_API_ACCESS_KEY`. It permits only bucket discovery,
upload, multipart-upload support, and cleanup of source objects; it does not
grant access to the artifact bucket or administrative actions.

In the MinIO Console:

1. Go to **Buckets** and create `rag-source` if it does not exist.
2. Go to **Identity → Policies**, create a policy from the contents of
   `deploy/minio/rag-api-upload-policy.json`, and name it `rag-api-upload`.
3. Go to **Identity → Users** (or **Access Keys**, depending on the Console
   version), select the user/access key configured as `RAG_MINIO_API_ACCESS_KEY`,
   and attach `rag-api-upload`.

With the MinIO Client (`mc`) installed, an administrator can perform the same
operation. Replace only the placeholder values locally; never commit them:

```powershell
mc alias set local http://localhost:9000 <MINIO_ROOT_USER> <MINIO_ROOT_PASSWORD>
mc mb --ignore-existing local/rag-source
mc admin policy create local rag-api-upload deploy/minio/rag-api-upload-policy.json
mc admin policy attach local rag-api-upload --user <RAG_MINIO_API_ACCESS_KEY>
```

If your MinIO Client reports that `policy create` is unknown, use the older
equivalent command `mc admin policy add` instead. Re-run the `head_bucket`
preflight check after attaching the policy; it must pass before submitting a
document. Restart the API debug session only if you changed its credentials,
not when changing the server-side policy.

## Debug FastAPI locally

For a debugger that honours breakpoints, use the VS Code Python extension:

1. Open the repository root in VS Code and select the interpreter managed by
   `uv` in `.venv`.
2. Open **Run and Debug**, create a `launch.json`, and add this configuration:

   ```json
   {
     "name": "Debug RAG document API",
     "type": "debugpy",
     "request": "launch",
     "module": "uvicorn",
     "args": [
       "rag_ingestion.interfaces.api:app",
       "--host", "127.0.0.1",
       "--port", "8000",
       "--log-level", "debug"
     ],
     "cwd": "${workspaceFolder}",
     "justMyCode": true
   }
   ```

3. Set a breakpoint in `submit_document` in
   `src/rag_ingestion/interfaces/api.py` and press **F5**.

Do not use `--reload` in the debugger launch configuration: it creates a child
process and can prevent breakpoints from binding reliably. Stop and restart the
debug session after code changes. For terminal-only diagnosis, retain
`--reload` and add `--log-level debug` to the `uvicorn` command.

If VS Code prints only `Aborted!` before Uvicorn starts, it is a native-process
crash rather than a FastAPI exception. The launch configuration enables Python's
fault handler so the integrated terminal will print the crashing extension or
thread. This has been observed with the Python 3.14/debugger combination even
when the same application starts normally outside the debugger. Recreate the
development virtual environment with Python 3.13, then select it in VS Code:

```powershell
# This replaces the existing .venv. Stop Uvicorn and close terminals using it first.
uv python install 3.13
uv venv --clear --python 3.13
uv sync --extra dev
```

Confirm the interpreter before pressing F5:

```powershell
uv run python --version
```

It should report Python 3.13.x. The project supports Python 3.11 and newer, so
this change does not alter the application code or its production behavior.

## Consistency boundary

Object storage is outside PostgreSQL's transaction. The API uploads the object
first, then commits the document/version/outbox rows atomically. If that
database transaction fails, it makes a best-effort delete of the newly-uploaded
object. No Kafka publication happens in the HTTP request; the outbox publisher
is the only component that publishes the committed event.
