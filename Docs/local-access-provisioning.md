# Local Access Provisioning

## Where secrets are saved

The worker configuration files are committed under `config/workers/` and do
not need to be generated. Each selects a database login and a Qdrant
permission while resolving its password/key from
`secrets/local-runtime-secrets.env`.

The optional local provisioner remains available for creating PostgreSQL
logins and generating local passwords when you are ready to use it:

```powershell
.\scripts\provision_local_access.ps1 -PrepareOnly
```

It creates or updates `secrets/local-runtime-secrets.env`, containing PostgreSQL passwords and Qdrant API keys. The same file also holds the manually supplied MinIO service credentials. The committed worker profiles remain separate and contain no credentials. Back up the runtime-secrets file only in an approved local secret store; do not send it in chat, add it to a ticket, or commit it.

The committed [template](../secrets/local-runtime-secrets.env.template) contains names only and no usable credentials.

## PostgreSQL logins created

| Login user | Used by | Group role | Connection limit |
| --- | --- | --- | --- |
| `rag_migration_login` | Controlled migration job | `rag_ingestion_migrator` | 2 |
| `rag_document_fetcher` | Fetch worker | `rag_ingestion_runtime` | 4 |
| `rag_content_extractor` | Docling worker | `rag_ingestion_runtime` | 4 |
| `rag_chunker` | Chunking worker | `rag_ingestion_runtime` | 4 |
| `rag_embedder` | BGE-M3 worker | `rag_ingestion_runtime` | 4 |
| `rag_indexer` | Qdrant indexing worker | `rag_ingestion_runtime` | 4 |
| `rag_outbox_publisher` | Kafka outbox publisher | `rag_ingestion_outbox_publisher` | 2 |
| `rag_query_api` | Retrieval/query API | `rag_ingestion_query_reader` | 8 |

The script creates or rotates passwords but never prints them. After PostgreSQL
is healthy, run the script without `-PrepareOnly`; it applies the two idempotent
metadata/privilege migrations before creating logins.

```powershell
.\scripts\provision_local_access.ps1
```

## Qdrant keys

The script generates these base keys in the same ignored file:

| Key | Use |
| --- | --- |
| `QDRANT_ADMIN_API_KEY` | Collection bootstrap and indexing writes only |
| `QDRANT_READ_ONLY_API_KEY` | Query-only service access |

Restart the local stack so Qdrant receives the generated keys:

```powershell
docker compose -f deploy/docker/docker-compose.yml --env-file config/env/container.env --env-file secrets/local-runtime-secrets.env up -d --force-recreate qdrant bootstrap-init
```

For the indexing worker, start Compose with the same two files. Later environment files override earlier ones, so the generated secrets replace development-template placeholders.

```powershell
docker compose -f deploy/docker/docker-compose.yml -f deploy/docker/docker-compose.workers.yml --env-file config/env/container.env --env-file secrets/local-runtime-secrets.env --env-file config/workers/document-fetcher.env --profile workers up --build
```

For a specific worker, add its generated worker file last. It overrides the shared development database DSN with the dedicated PostgreSQL login:

```powershell
docker compose -f deploy/docker/docker-compose.yml -f deploy/docker/docker-compose.workers.yml --env-file config/env/container.env --env-file secrets/local-runtime-secrets.env --env-file config/workers/indexer.env --profile workers up --build
```

Use the matching file for `document-fetcher`, `content-extractor`, `chunker`, `embedder`, `indexer`, or `outbox-publisher`. The indexer receives the Qdrant admin key; other worker settings receive the read-only key by default.

For production, create collection-scoped Qdrant JWT keys (read-only for query APIs, read/write for the indexer) in the secured Qdrant administration workflow. Do not use the global admin key in query services.

## Production ownership and rollout

Keep PostgreSQL schema migrations under `migrations/`; they are versioned and
must contain no credentials. Keep the idempotent service-login definition at
`deploy/postgresql/provision-service-logins.sql`. Run that file from a
restricted infrastructure/deployment job as the database administrator, with
the eight password variables injected from the production secret manager. Do
not give the application migration login permission to create roles.

Keep the Qdrant collection contract in `scripts/bootstrap_qdrant.py` and run
it from the same restricted deployment job using an admin credential. It
creates `rag_chunks_bge_m3_v1`, its named `dense` (1,024-dimension cosine) and
`sparse` vectors, and indexes the metadata used for tenant/ACL filtering. The
point payload is documented in `Docs/data-storage.md`; it must not contain
chunk text, source URLs, or other sensitive content.

Issue credentials by actual access need:

| Component | PostgreSQL login | Qdrant credential |
| --- | --- | --- |
| Migration/collection bootstrap | `rag_migration_login` | admin (deployment job only) |
| Document fetcher, extractor, chunker, embedder, outbox publisher | matching worker login | none |
| Indexer | `rag_indexer` | collection write JWT (admin only for local development) |
| Query API | `rag_query_api` | collection read JWT (read-only key only for local development) |

For a rotation, create a new secret version, roll the affected workload, test
its health, then revoke the old credential. Apply database roles and Qdrant
collection changes through CI/CD with an audit trail; never run them manually
from a developer workstation against production.

## Rotate local credentials

```powershell
.\scripts\provision_local_access.ps1 -Rotate
docker compose -f deploy/docker/docker-compose.yml --env-file config/env/container.env --env-file secrets/local-runtime-secrets.env up -d --force-recreate qdrant bootstrap-init
```

Rotating PostgreSQL passwords requires restarting worker containers so they load the new values. Production rotation must be executed through the secret manager and deployment platform, using overlapping credentials where supported.
