# Work item: Reject oversized document uploads

- Recorded at: 2026-08-02T12:14:34+05:00
- Status: completed

## Prompt

> please implement your suggestion .

## Outcome

Added a configurable document-upload limit to the FastAPI submission endpoint.
The default is 50 MiB (`52428800` bytes), matching the current document-fetcher
maximum size so the API does not accept documents that the next processing stage
would reject.

## Implementation

- Added `RAG_API_MAX_UPLOAD_BYTES` / `Settings.api_max_upload_bytes`.
- Added a middleware `Content-Length` check for `POST /v1/documents`, returning
  `413 Payload Too Large` before multipart parsing when the declared request
  size exceeds the configured limit.
- Added exact streamed file-byte enforcement while hashing the upload. This
  catches clients that omit or falsify `Content-Length` and happens before the
  file can be sent to MinIO.
- Added user documentation for configuring and interpreting the upload limit.
- Added a settings unit test for the configurable limit.

## Validation

- Ruff passed for `src` and `tests`.
- `git diff --check` passed.
- Pytest could not run in this sandbox because executing the repository
  `.venv` Python executable is denied by the environment; run
  `uv run pytest tests/unit/test_settings.py -q` locally to verify the new
  settings test.
