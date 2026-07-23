# Worker profiles

Each committed `.env` file chooses a worker identity and maps it to the
corresponding password and Qdrant permission from
`secrets/local-runtime-secrets.env`. These profiles contain no usable
credentials and do not require `provision_local_access.ps1` to be generated.

Pass exactly one profile after the container profile and runtime secrets file:

```powershell
docker compose -f deploy/docker/docker-compose.yml -f deploy/docker/docker-compose.workers.yml --env-file config/env/container.env --env-file secrets/local-runtime-secrets.env --env-file config/workers/document-fetcher.env --profile workers up --build
```

The matching PostgreSQL login must still be created before the worker can
connect. Apply the database migrations, then run
`deploy/postgresql/provision-service-logins.sql` under a database-admin
identity (or use the optional local provisioning script). Only `migration` and
`indexer` receive the Qdrant admin key; `query-api` receives the read-only key.
The other workers have no Qdrant access.
