# Enterprise RAG Data Storage

## Data ownership

| Store | Authoritative data | Retrieval data |
| --- | --- | --- |
| PostgreSQL | Tenant, document/version lifecycle, ACLs, chunk lineage, idempotency, outbox, failures, and audit events | None |
| MinIO | Immutable source documents and normalized Docling artifacts | None |
| Qdrant | None | Dense and sparse chunk vectors plus filterable, non-sensitive payload |

PostgreSQL is the source of truth. Qdrant is a rebuildable, versioned retrieval projection. A changed embedding/indexing strategy must be recoverable by replaying document-version data, never by treating Qdrant as the only record.

## PostgreSQL migration

Apply [001_enterprise_rag_metadata.sql](../migrations/001_enterprise_rag_metadata.sql) using a migration runner under a privileged migration role. For local Docker development:

```powershell
Get-Content migrations/001_enterprise_rag_metadata.sql | docker compose -f deploy/docker/docker-compose.yml --env-file config/env/container.env --env-file secrets/local-runtime-secrets.env exec -T postgres psql -U rag -d rag_ingestion
```

The runtime application role must be distinct from the migration owner and issue `SET LOCAL app.tenant_id = '<tenant UUID>'` in every transaction. This activates PostgreSQL row-level-security policies.

Apply [002_database_roles_and_privileges.sql](../migrations/002_database_roles_and_privileges.sql) next. It defines four group roles: migration, runtime worker, outbox publisher, and query reader. It also exposes narrowly scoped security-definer functions for claiming and completing outbox events across tenants, so the publisher does not need blanket `BYPASSRLS` access.

## Qdrant hybrid collection

Run the bootstrap script after Python dependencies are installed and the `RAG_` settings are supplied:

```text
python scripts/bootstrap_qdrant.py
```

The default collection is `rag_chunks_bge_m3_v1`. Each point has two named vectors:

- `dense`: 1,024-dimensional BGE-M3 vector using cosine distance.
- `sparse`: BGE-M3 lexical sparse vector, using model-provided nonzero indices and weights.

Payload indexes cover tenant, ACL, lifecycle, document lineage, and provenance fields. Every retrieval query must filter on `tenant_id`, `is_active = true`, and a caller-derived ACL. Never place full chunk text, raw source paths, presigned URLs, or sensitive document content in Qdrant payloads.

## Indexing contract

Each Qdrant payload must carry stable IDs and authorization context:

```json
{
  "tenant_id": "<uuid>",
  "document_id": "<uuid>",
  "document_version_id": "<uuid>",
  "chunk_id": "<uuid>",
  "acl_principals": ["group:engineering"],
  "classification": "internal",
  "is_active": true,
  "embedding_model": "BAAI/bge-m3"
}
```

Use Qdrant prefetch plus reciprocal-rank fusion (RRF) for one hybrid request: retrieve dense and sparse candidates under the same filter and fuse their ranked lists. Do not add raw dense and sparse scores because they are not calibrated to the same scale.

## Database users and access control

### PostgreSQL

`002_database_roles_and_privileges.sql` intentionally creates **group roles without passwords**. The database administrator or secret manager creates login identities and grants exactly one group role to each:

| Login purpose | Group role | Capability |
| --- | --- | --- |
| Migration job | `rag_ingestion_migrator` | Schema migrations only |
| Ingestion workers | `rag_ingestion_runtime` | Tenant-scoped document, chunk, audit, failure, and outbox writes |
| Outbox publisher | `rag_ingestion_outbox_publisher` | Execute only the claim/complete outbox functions |
| Retrieval API | `rag_ingestion_query_reader` | Tenant-scoped lineage and ACL reads |

Do not use the PostgreSQL superuser or migration identity in an application container. Create login passwords/identity bindings outside Git, rotate them through the secret manager, and use a connection pool that resets session state after every transaction. Runtime logins inherit their assigned group role, but each tenant-bound transaction must still set `app.tenant_id`.

### Qdrant

Qdrant uses API keys and JWT collection permissions rather than database users. The local Compose stack enables:

| Credential | Environment variable | Intended use |
| --- | --- | --- |
| Admin key | `QDRANT_ADMIN_API_KEY` / `RAG_QDRANT_API_KEY` | Bootstrap and indexing workers; manages collections and writes points |
| Read-only key | `QDRANT_READ_ONLY_API_KEY` / `RAG_QDRANT_READ_ONLY_API_KEY` | Query-only services; cannot change collections or points |
| JWT collection token | Generated after enabling `QDRANT__SERVICE__JWT_RBAC` | Production service credentials scoped to a specific collection and read/write permission |

Use the admin key only for the restricted deployment bootstrap. The indexer
must receive a collection-write JWT; the query API must receive a
collection-read JWT. All other workers receive no Qdrant credential. For
production, terminate TLS before Qdrant or enable native TLS, restrict network
access, enable audit logging, and store keys only in a secret manager.

## 20–90 implementation baseline

This baseline covers the highest-value enterprise requirements: tenant isolation, ACL lineage, versioning, retention markers, auditability, transactional outbox, idempotent consumers, failure records, hybrid retrieval, filter indexes, and rebuildability. Deferred work includes cross-region replication, legal holds, automatic key rotation, retention jobs, CDC, replica/shard tuning, and reranking; add those from measured compliance, scale, and availability requirements.
