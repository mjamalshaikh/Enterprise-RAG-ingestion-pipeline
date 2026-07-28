# Local Access Provisioning

## Where secrets are saved

Copy `secrets/local-runtime-secrets.env.template` to the ignored
`secrets/local-runtime-secrets.env`. It holds the one PostgreSQL application
password, Qdrant keys, and MinIO credentials. Keep it in an approved local
secret store; never commit or share it.

## PostgreSQL application login

Every API and worker connects as `rag_application`. Set one strong,
URL-safe value for `POSTGRES_APPLICATION_PASSWORD`; the template’s host DSN
uses it automatically. Worker Compose configuration uses the same credential
against the Docker `postgres` hostname.

Apply the metadata and access migrations, including migration 004, as the
database/schema owner. Then provision the login as that administrator:

```powershell
Get-Content deploy/postgresql/provision-service-logins.sql |
  docker compose -f deploy/docker/docker-compose.yml --env-file config/env/container.env --env-file secrets/local-runtime-secrets.env exec -T postgres psql -v ON_ERROR_STOP=1 -U rag -d rag_ingestion
```

`rag_application` has full access to `rag` tables, sequences, functions, and
types but does not own them and cannot create objects in `rag`. In PostgreSQL,
only an owner or superuser can drop an artifact, so this prevents application
processes from dropping database artifacts. The provisioning script also
disables old per-service logins if they exist.

Use the static `scripts/create-rag-postgres-users.psql` only for a manual
psql/pgAdmin-style local setup; replace its placeholder password first.

## Qdrant keys

Qdrant uses API keys/JWTs rather than PostgreSQL users. The same local secret
file contains `QDRANT_ADMIN_API_KEY` for bootstrap/indexing and
`QDRANT_READ_ONLY_API_KEY` for query services. Production should use
collection-scoped JWTs and store all credentials in the deployment secret
manager.

## Run a worker

```powershell
docker compose -f deploy/docker/docker-compose.yml -f deploy/docker/docker-compose.workers.yml --env-file config/env/container.env --env-file secrets/local-runtime-secrets.env --env-file config/workers/document-fetcher.env --profile workers up --build
```

All profiles in this command use `rag_application`; they differ only by worker
name and Qdrant access.
