# Enterprise RAG Ingestion Pipeline

An event-driven Python foundation for ingesting enterprise documents (such as PDF and DOCX) into a RAG-ready index.

## Selected platform

| System | Role |
| --- | --- |
| IBM Docling | PDF/DOCX conversion and structured content extraction |
| MinIO | S3-compatible storage for source and normalized document artifacts |
| PostgreSQL | Document metadata, idempotency keys, transactional outbox, and Apicurio storage |
| Kafka | Durable asynchronous pipeline events, retries, and dead-letter topics |
| Apicurio Registry | Versioned Avro event contracts for Kafka producers and consumers |
| BGE-M3 | Multilingual dense, sparse, and multi-vector embedding model |
| Qdrant | Tenant-filtered vector and payload index |
| OpenTelemetry Collector | Receives, enriches, and routes application telemetry |
| Prometheus | Metrics storage and alert-rule evaluation |
| Loki | Centralized structured log storage |
| Grafana | Provisioned dashboards, alerting, and telemetry exploration |

## Local platform

1. Review `config/env/host.env` (host Python) and `config/env/container.env` (Docker workers). These profiles are committed because they contain no secrets.
2. Create `secrets/local-runtime-secrets.env` from `secrets/local-runtime-secrets.env.template` and populate the local credentials.
3. Start the backing services with `docker compose -f deploy/docker/docker-compose.yml --env-file config/env/container.env --env-file secrets/local-runtime-secrets.env up -d`.
4. Install the application with `pip install -e ".[dev]"` after Python 3.11+ is available.

The Compose stack is strictly for local development. Production deployments must use managed secrets, TLS, authenticated Kafka, and multi-node storage/database/vector clusters.

Local observability endpoints: Grafana `http://localhost:3000`, Prometheus `http://localhost:9090`, Loki `http://localhost:3100`, and OTLP gRPC `localhost:4317` / HTTP `localhost:4318`.

## Portable worker runtime

Workers are built once as OCI images and configured at runtime through `RAG_` environment variables. Run the local worker profile after worker modules are implemented:

```text
docker compose -f deploy/docker/docker-compose.yml -f deploy/docker/docker-compose.workers.yml --env-file config/env/container.env --env-file secrets/local-runtime-secrets.env --env-file config/workers/document-fetcher.env --profile workers up --build
```

Kubernetes deployments are rendered from [the Helm chart](deploy/helm/rag-ingestion). The chart is cloud-neutral: it references a pre-created runtime Secret and accepts service endpoints as values. See [cloud-portability.md](Docs/cloud-portability.md) before selecting AWS-managed equivalents.

See [the architecture](Docs/architecture.md) for the intended ports-and-adapters design and event flow.
See [development-environment.md](Docs/development-environment.md) for the local Docker Desktop environment, service endpoints, and startup checks.
See [data-storage.md](Docs/data-storage.md) for the PostgreSQL metadata schema and BGE-M3 dense/sparse Qdrant collection bootstrap.
See [local-access-provisioning.md](Docs/local-access-provisioning.md) to create local database logins and Qdrant API keys without committing secrets.
See [docker-desktop-integration.md](Docs/docker-desktop-integration.md) to connect to the already-running Docker Desktop services without host-port conflicts.
