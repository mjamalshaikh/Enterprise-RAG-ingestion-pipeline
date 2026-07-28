# Worker profiles

Each committed `.env` file selects a worker and its Qdrant permission. All
workers use the one `rag_application` PostgreSQL login, whose password comes
from `POSTGRES_APPLICATION_PASSWORD` in `secrets/local-runtime-secrets.env`.
These profiles contain no usable credentials.

Pass exactly one profile after the container profile and runtime secrets file:

```powershell
docker compose -f deploy/docker/docker-compose.yml -f deploy/docker/docker-compose.workers.yml --env-file config/env/container.env --env-file secrets/local-runtime-secrets.env --env-file config/workers/document-fetcher.env --profile workers up --build
```

Create the single PostgreSQL login before workers connect: apply migrations
through `004_single_application_database_user.sql`, then run
`deploy/postgresql/provision-service-logins.sql` as a database administrator.
Only `migration` and
`indexer` receive the Qdrant admin key; `query-api` receives the read-only key.
The other workers have no Qdrant access.
