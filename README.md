# Enterprise RAG Ingestion Pipeline

An event-driven Python foundation for ingesting enterprise documents (such as PDF and DOCX) into a RAG-ready index.

## Selected platform

| System | Role |
| --- | --- |
| IBM Docling | PDF/DOCX conversion and structured content extraction |
| MinIO | S3-compatible storage for source and normalized document artifacts |
| PostgreSQL | Document metadata, idempotency keys, and transactional outbox |
| Kafka | Durable asynchronous pipeline events, retries, and dead-letter topics |
| Checked-in Avro schemas | Versioned event contracts for Kafka producers and consumers |
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

Avro contracts are checked into `schemas/avro`. Schema changes must be reviewed
with every producer and consumer, and the event's `schema_version` is sent in
each Kafka record header.

Kafka topic creation is also explicit. The bundled platform initializer runs it
automatically; when using the shared Docker Desktop Kafka broker, run
`python scripts/bootstrap_kafka.py` once before the outbox publisher.

The Compose stack is strictly for local development. Production deployments must use managed secrets, TLS, authenticated Kafka, and multi-node storage/database/vector clusters.

Local observability endpoints: Grafana `http://localhost:3000`, Prometheus `http://localhost:9090`, Loki `http://localhost:3100`, and OTLP gRPC `localhost:4317` / HTTP `localhost:4318`.

`RAG_OBSERVABILITY_MODE` selects telemetry destinations. `console` writes logs,
enabled traces, and periodic metrics to the process console; `otlp` sends all
three signals to `RAG_OTEL_EXPORTER_OTLP_ENDPOINT`; and `console_and_otlp`
writes logs to the console while also sending logs, enabled traces, and metrics
to OTLP. `RAG_TRACING_ENABLED` controls whether
trace spans are created at all. Worker message and outbox delivery counters are
exported every `RAG_OTEL_METRICS_EXPORT_INTERVAL_SECONDS` (15 seconds by
default). Host processes use `config/env/host.env` by default and container
workers select `config/env/container.env` via `RAG_CONFIG_PROFILE=container`.
In OTLP mode, open Grafana at `http://localhost:3000` to query Loki logs,
Tempo traces, and Prometheus metrics.

## Portable worker runtime

Workers are built once as OCI images and configured at runtime through `RAG_` environment variables. The currently implemented PDF path is the outbox publisher, document fetcher, and content extractor. Start the extractor with its dedicated profile after applying migration 006:

```powershell
docker compose -f deploy/docker/docker-compose.yml -f deploy/docker/docker-compose.workers.yml --env-file config/env/container.env --env-file secrets/local-runtime-secrets.env --env-file config/workers/content-extractor.env --profile workers up --build rag-worker
```

Run the outbox publisher and document fetcher in separate terminals (using their matching profiles) to deliver a submitted PDF to the extractor. The extractor consumes `DocumentFetched`, writes normalized and manifest JSON to `rag-artifacts`, and emits `ContentExtracted` for a future chunker. It retains figure/picture anchors and captions but does not generate visual descriptions.

Kubernetes deployments are rendered from [the Helm chart](deploy/helm/rag-ingestion). The chart is cloud-neutral: it references a pre-created runtime Secret and accepts service endpoints as values. See [cloud-portability.md](Docs/cloud-portability.md) before selecting AWS-managed equivalents.

See [the architecture](Docs/architecture.md) for the intended ports-and-adapters design and event flow.
See [development-environment.md](Docs/development-environment.md) for the local Docker Desktop environment, service endpoints, and startup checks.
See [data-storage.md](Docs/data-storage.md) for the PostgreSQL metadata schema and BGE-M3 dense/sparse Qdrant collection bootstrap.
See [local-access-provisioning.md](Docs/local-access-provisioning.md) to create the shared local database login and Qdrant API keys without committing secrets.
See [docker-desktop-integration.md](Docs/docker-desktop-integration.md) to connect to the already-running Docker Desktop services without host-port conflicts.
See [document-submission-api.md](Docs/document-submission-api.md) to run the FastAPI upload endpoint and submit a document from its client, cURL, Postman, or Swagger UI.
