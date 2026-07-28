# Technology Stack

## Service ownership

| System | Data owned | Production expectations |
| --- | --- | --- |
| IBM Docling | No durable state; produces normalized document output | Run as isolated workers with resource limits; pin models and record their version in metadata. |
| MinIO | Original documents and derived extraction artifacts | Versioned buckets, server-side encryption, lifecycle policies, tenant-scoped prefixes, and backup replication. |
| PostgreSQL | Metadata, idempotency ledger, and outbox | HA deployment, encrypted backups, migrations, connection pooling, and point-in-time recovery. |
| Kafka | Pipeline commands/events, retries, and DLQs | Three or more brokers, TLS/SASL, ACLs, replication factor >= 3, monitoring, and retention policy per topic. |
| Checked-in Avro schemas | Event contracts | Version schemas with the producers and consumers that use them; review compatibility before release. |
| BGE-M3 | Model cache only; embeddings are persisted in Qdrant | Isolate model-serving workers, select CPU/GPU via deployment profile, and version the model in each vector payload. |
| Qdrant | Vectors plus non-sensitive chunk metadata | Cluster mode, API-key/TLS protection, snapshots, and collection aliases for zero-downtime reindexing. |
| OpenTelemetry Collector | Telemetry in transit | Run as a gateway deployment with memory limits, batching, tail sampling policy, TLS, and authenticated exporters. |
| Prometheus | Metrics and alert-rule state | Highly available pair, durable remote-write backend for long retention, alert routing, and restricted scrape endpoints. |
| Loki | Structured application logs | Object-store-backed deployment, retention policies, tenant isolation, and restrictive labels to control cardinality. |
| Grafana | Dashboards, alerting configuration, and user access | OIDC, RBAC, provisioned data sources/dashboards, encrypted secrets, and audit logging. |

## Kafka topic convention

All topics begin with `rag.ingestion.v1` and use Avro values encoded from checked-in schemas.

| Topic | Producer | Consumer |
| --- | --- | --- |
| `rag.ingestion.v1.document.submitted` | Submission API | Fetch worker |
| `rag.ingestion.v1.document.fetched` | Fetch worker | Extraction worker |
| `rag.ingestion.v1.content.extracted` | Docling worker | Chunking worker |
| `rag.ingestion.v1.chunks.created` | Chunking worker | Embedding worker |
| `rag.ingestion.v1.embeddings.generated` | Embedding worker | Indexing worker |
| `rag.ingestion.v1.document.indexed` | Indexing worker | Lifecycle/audit consumers |
| `rag.ingestion.v1.<stage>.retry` | Retry policy | Original stage worker |
| `rag.ingestion.v1.<stage>.dlq` | Failed stage worker | Operations tooling |

Kafka record keys are `tenant_id:document_id`. Headers include `event_id`, `correlation_id`, `causation_id`, `tenant_id`, `schema_version`, and W3C `traceparent`.

The checked-in `scripts/bootstrap_kafka.py` creates these topics explicitly.
Local development uses one partition and one replica; production must set
`RAG_KAFKA_TOPIC_PARTITIONS` and `RAG_KAFKA_TOPIC_REPLICATION_FACTOR` to the
reviewed cluster values before bootstrapping. Existing topic settings are never
mutated by the script.

## Security baseline

- Never put document bytes or sensitive extracted text in Kafka; carry object references and metadata only.
- Use per-environment credentials injected by a secret manager; `.env` exists only for local development.
- Apply authorization at ingress and propagate a verified `tenant_id` rather than trusting caller-provided values.
- Encrypt network traffic and storage, redact PII from logs, and use time-limited presigned URLs for document access.
- Emit structured JSON logs with `tenant_id`, `document_id`, `event_id`, `correlation_id`, and `trace_id`; never log document text, tokens, access keys, or presigned URLs.

## Observability signal routing

```text
RAG API and workers --OTLP--> OpenTelemetry Collector --metrics--> Prometheus --query--> Grafana
                                             |--logs--> Loki ---------------------------^
                                             `--traces--> configured trace backend
```

The local stack includes only metrics and logs backends. The Collector accepts traces and debug-exports them locally until a production trace backend is selected.
