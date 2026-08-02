# Worker profiles

Each committed `.env` file selects a worker and its Qdrant permission. All
workers use the one `rag_application` PostgreSQL login, whose password comes
from `POSTGRES_APPLICATION_PASSWORD` in `secrets/local-runtime-secrets.env`.
These profiles contain no usable credentials.

The worker launcher automatically loads the matching profile. For example,
`uv run python -m rag_ingestion.workers --worker outbox-publisher` loads
`config/workers/outbox-publisher.env`; no separate `--env-file` argument is
needed for a direct host run.

Pass exactly one profile after the container profile and runtime secrets file. For example, start the PDF content extractor with:

```powershell
docker compose -f deploy/docker/docker-compose.yml -f deploy/docker/docker-compose.workers.yml --env-file config/env/container.env --env-file secrets/local-runtime-secrets.env --env-file config/workers/content-extractor.env --profile workers up --build rag-worker
```

Run `outbox-publisher`, `document-fetcher`, and `content-extractor` as separate worker containers, each with its matching profile. The content extractor consumes `DocumentFetched`; it therefore remains idle until the publisher has delivered an upload event and the fetcher has emitted a validated PDF event.

For direct host development, run the same stages in separate PowerShell terminals:

```powershell
uv run python -m rag_ingestion.workers --worker outbox-publisher 2>&1 | Tee-Object -FilePath .\logs\outbox-publisher -Append
uv run python -m rag_ingestion.workers --worker document-fetcher 2>&1 | Tee-Object -FilePath .\logs\document-fetcher.log -Append
uv run python -m rag_ingestion.workers --worker content-extractor 2>&1 | Tee-Object -FilePath .\logs\content-extractor.log -Append
```

Create the single PostgreSQL login before workers connect: apply migrations
through `004_single_application_database_user.sql`, then run
`deploy/postgresql/provision-service-logins.sql` as a database administrator.
Only `migration` and
`indexer` receive the Qdrant admin key; `query-api` receives the read-only key.
The other workers have no Qdrant access.

## Observability contract for workers

Every polling worker must use `WorkerTelemetry` from
`rag_ingestion.infrastructure.observability`:

1. Call `poll_started()` immediately before every poll and `poll_finished()`
   with a bounded outcome such as `empty`, `message`, `events`, or `error`.
   This emits a console/OTLP log and the `rag.ingestion.worker.polls` metric.
2. Wrap actual message or event processing in `processing()`. This creates a
   trace span without creating trace noise for empty polls.
3. Record completed message outcomes with `record_worker_message()` where the
   worker consumes messages.

This contract applies to all future workers as well as the outbox publisher
and document fetcher.
