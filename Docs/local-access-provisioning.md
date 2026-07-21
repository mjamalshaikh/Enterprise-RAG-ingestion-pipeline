# Local Access Provisioning

## Where secrets are saved

Before the first local Compose startup, prepare the secret file and worker
files without contacting Docker:

```powershell
.\scripts\provision_local_access.ps1 -PrepareOnly
```

It creates `secrets/local-access.env`, containing generated PostgreSQL passwords and Qdrant API keys. The same file also holds the manually supplied MinIO service credentials. It creates one connection file for each worker under `secrets/workers/`. Both locations are ignored by Git. Back them up only in an approved local secret store; do not send them in chat, add them to a ticket, or commit them.

The committed [template](../secrets/local-access.env.example) contains names only and no usable credentials.

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
docker compose -f deploy/docker/docker-compose.yml --env-file config/env/container.env --env-file secrets/local-access.env up -d --force-recreate qdrant bootstrap-init
```

For the indexing worker, start Compose with the same two files. Later environment files override earlier ones, so the generated secrets replace development-template placeholders.

```powershell
docker compose -f deploy/docker/docker-compose.yml -f deploy/docker/docker-compose.workers.yml --env-file config/env/container.env --env-file secrets/local-access.env --profile workers up --build
```

For a specific worker, add its generated worker file last. It overrides the shared development database DSN with the dedicated PostgreSQL login:

```powershell
docker compose -f deploy/docker/docker-compose.yml -f deploy/docker/docker-compose.workers.yml --env-file config/env/container.env --env-file secrets/local-access.env --env-file secrets/workers/indexer.env --profile workers up --build
```

Use the matching file for `document-fetcher`, `content-extractor`, `chunker`, `embedder`, `indexer`, or `outbox-publisher`. The indexer receives the Qdrant admin key; other worker settings receive the read-only key by default.

For production, create collection-scoped Qdrant JWT keys (read-only for query APIs, read/write for the indexer) in the secured Qdrant administration workflow. Do not use the global admin key in query services.

## Rotate local credentials

```powershell
.\scripts\provision_local_access.ps1 -Rotate
docker compose -f deploy/docker/docker-compose.yml --env-file config/env/container.env --env-file secrets/local-access.env up -d --force-recreate qdrant bootstrap-init
```

Rotating PostgreSQL passwords requires restarting worker containers so they load the new values. Production rotation must be executed through the secret manager and deployment platform, using overlapping credentials where supported.
