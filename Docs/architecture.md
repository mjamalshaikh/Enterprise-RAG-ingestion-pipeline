# Architecture

The pipeline uses a ports-and-adapters structure and treats every processing boundary as an asynchronous domain event.

## Layout

| Path | Responsibility |
| --- | --- |
| `src/rag_ingestion/domain` | Event contracts and infrastructure-neutral ports |
| `src/rag_ingestion/application` | Pipeline orchestration and use cases |
| `src/rag_ingestion/infrastructure` | Broker, storage, parser, embedding, and vector-store adapters |
| `src/rag_ingestion/interfaces` | CLI, HTTP API, and other inbound entry points |
| `src/rag_ingestion/workers` | Long-lived broker consumers |
| `deploy` | Container and Kubernetes/Helm deployment definitions |
| `deploy/docker/Dockerfile` | Portable OCI worker image definition |
| `deploy/helm/rag-ingestion` | Cloud-neutral Helm deployment for a single worker type |
| `infra/terraform` | Cloud infrastructure modules and environment composition |
| `migrations` | Database migrations for metadata, idempotency, and outbox records |
| `Docs/runbooks` | Operational incident and recovery procedures |
| `Docs/adr` | Architecture decision records |
| `tests/unit` | Isolated domain/application tests |
| `tests/contract` | Port-to-adapter compatibility tests |
| `tests/integration` | Adapter integration tests |
| `tests/e2e` | Full ingestion workflow tests |
| `tests/performance` | Throughput and load tests |

## Event flow

1. `DocumentSubmitted`
2. `DocumentFetched`
3. `ContentExtracted`
4. `ChunksCreated`
5. `EmbeddingsGenerated`
6. `DocumentIndexed`

Production adapters should preserve `event_id`, `correlation_id`, and `tenant_id`; they support tracing, idempotency, and tenant isolation. Add retry, dead-letter, and outbox behavior at the broker adapter boundary.

## Selected technology bindings

| Boundary | Technology | Responsibility |
| --- | --- | --- |
| Content extraction | IBM Docling | Convert PDF and DOCX into normalized structured content; retain source location and extraction metadata. |
| Object storage | MinIO | Persist immutable originals and derived Docling artifacts in separate, tenant-prefixed buckets. |
| Transactional state | PostgreSQL | Store document lifecycle state, idempotency keys, outbox records, and audit metadata. |
| Event transport | Apache Kafka | Carry durable stage events; use retry and DLQ topics per consumer stage. |
| Event contracts | Checked-in Avro schemas | Govern reviewed, backward-compatible Avro contracts for every Kafka topic. |
| Embeddings | BAAI BGE-M3 | Produce multilingual dense vectors initially; retain the option to add sparse and ColBERT retrieval later. |
| Vector index | Qdrant | Store vectors and document/chunk payloads; enforce every query and upsert with `tenant_id` filters. |
| Telemetry intake | OpenTelemetry Collector | Receive OTLP telemetry, add deployment metadata, and route signals without coupling workers to a backend. |
| Metrics | Prometheus | Scrape Collector/application metrics and evaluate recording/alert rules. |
| Logs | Loki | Store structured worker and API logs, correlated with trace and event identifiers. |
| Telemetry UI | Grafana | Provision data sources, dashboards, and alerts as version-controlled configuration. |

### Persistence and delivery guarantees

1. Write a document state transition and its outbox row in one PostgreSQL transaction.
2. An outbox publisher sends the registered Avro event to Kafka, keyed by `tenant_id:document_id`.
3. Consumers record idempotency by `event_id` before external side effects and acknowledge only after success.
4. Transient failures are retried through retry topics; exhausted events go to a stage-specific DLQ with the original headers preserved.
5. Schema versions are propagated in Kafka headers. Producers and consumers deploy compatible checked-in Avro contracts together.

See [technology-stack.md](technology-stack.md) for operational configuration and ownership.

## Runtime portability

The domain and application layers depend only on ports. Infrastructure adapters implement those ports for the selected systems, and deployment configuration supplies endpoints and credentials at runtime. This permits a staged move to AWS (for example, S3-compatible object storage, managed PostgreSQL, managed Kafka, and managed Kubernetes) without importing cloud-provider SDKs into domain logic. See [cloud-portability.md](cloud-portability.md).
