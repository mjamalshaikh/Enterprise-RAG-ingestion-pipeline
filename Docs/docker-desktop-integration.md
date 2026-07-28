# Docker Desktop Integration

## Reviewed local services

The repository was aligned with the Compose files supplied from the local Docker Desktop environment. The project keeps Qdrant as its selected vector database; Milvus and Neo4j are available locally but are not automatically enabled as pipeline dependencies.

| System | Host endpoint | Docker `internal_network` endpoint | Repository use |
| --- | --- | --- | --- |
| Kafka 4.1 | `localhost:29092` | `kafka:9092` | Required event broker |
| Kafka UI | `localhost:8092` | `kafka-ui:8080` | Local operations only |
| PostgreSQL | `localhost:5432` | `postgres:5432` | Required metadata/outbox database |
| Keycloak | `localhost:8090` | `keycloak:8080` | Optional OIDC provider for future API authentication |
| MinIO | `localhost:9000` | `minio:9000` | Required object storage |
| MinIO Console | `localhost:9001` | `minio:9001` | Local operations only |
| OpenTelemetry Collector | `localhost:4317` / `4318` | `otel-collector:4317` / `4318` | Required telemetry gateway |
| Prometheus | `localhost:9090` | `prometheus:9090` | Metrics backend |
| Loki | `localhost:3100` | `loki:3100` | Logs backend |
| Tempo | `localhost:3200` | `tempo:3200` | Trace backend |
| Grafana | `localhost:3000` | `grafana:3000` | Telemetry UI |
| Neo4j | `localhost:7474` / `7687` | Not on `internal_network` | Optional future GraphRAG integration |
| Milvus | `localhost:19530` | Not on `internal_network` | Not used; Qdrant remains the vector store |
| Project Qdrant | `localhost:6333` / `6334` | `qdrant:6333` / `6334` | Required hybrid vector store |

## Avoid duplicate containers and port conflicts

Do not start the repository's bundled PostgreSQL, Kafka, MinIO, or observability services when the corresponding local Docker Desktop stacks are already running. They bind the same host ports.

The project worker and project Qdrant service now attach to the existing external Docker network `internal_network`. Confirm it exists before starting them:

```powershell
docker network inspect internal_network
```

Use the committed `config/env/container.env` profile together with the ignored `secrets/local-runtime-secrets.env` file, then start only Qdrant from this repository:

```powershell
docker compose -f deploy/docker/docker-compose.yml --env-file config/env/container.env --env-file secrets/local-runtime-secrets.env up -d qdrant
```

The MinIO identities are deliberately kept outside tracked configuration.
`ingestion-service` is the worker identity and `rag-api` is the API identity;
their credentials belong in the ignored `secrets/local-runtime-secrets.env` file.
Pass that file after the endpoint environment file so the local secrets
override its placeholders.

Start an implemented worker without Compose starting duplicate dependencies:

```powershell
docker compose -f deploy/docker/docker-compose.yml -f deploy/docker/docker-compose.workers.yml --env-file config/env/container.env --env-file secrets/local-runtime-secrets.env --env-file config/workers/document-fetcher.env --profile workers up --build rag-worker
```

## PostgreSQL prerequisites

The existing PostgreSQL Compose definition is configured for Keycloak's `keycloak_db`, not this pipeline's `rag_ingestion` database. Before a worker can connect, provision a separate `rag_ingestion` database and the RAG roles/logins on that PostgreSQL server. Do not point pipeline migrations at Keycloak's database or use the Keycloak database login.

The pipeline uses checked-in Avro schemas and does not require a schema registry.

## Optional systems

Neo4j and Milvus are deliberately not added to application settings or workers because they were not selected as required pipeline stores. If Neo4j is adopted for GraphRAG, first attach it to `internal_network`, use `bolt://neo4j:7687` for containers, and add it through a dedicated graph-store port. Do not run both Milvus and Qdrant for the same retrieval projection without an explicit dual-write and migration plan.
