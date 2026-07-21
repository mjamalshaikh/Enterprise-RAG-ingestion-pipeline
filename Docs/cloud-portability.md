# Cloud Portability and Runtime Strategy

## Decision

The ingestion pipeline remains cloud agnostic while keeping AWS as a future deployment target. It runs workers as OCI containers locally with Docker and in production on conformant Kubernetes clusters. Cloud-specific resources are provisioned outside the application chart and are connected through runtime configuration and Secrets.

## Rules

1. Keep cloud-provider SDKs out of `domain` and `application`. Provider integration belongs behind an infrastructure port.
2. Use open protocols at boundaries: S3-compatible object storage, PostgreSQL wire protocol, Kafka, OTLP, Prometheus exposition, and standard Kubernetes APIs.
3. Build one immutable worker image per commit and promote the same image through local, test, and production environments.
4. Supply URLs, credentials, certificates, and deployment metadata only through environment variables, mounted files, or workload identity; never bake them into images or Helm values.
5. Keep the Helm chart free of cloud resource definitions. Terraform/environment composition owns cloud-specific services, networking, identities, DNS, and secret-manager integration.

## Deployment model

| Layer | Local | Kubernetes / future AWS |
| --- | --- | --- |
| Worker runtime | Docker Compose profile and the project OCI image | Helm `Deployment`; one release or values file per worker stage |
| Object storage | MinIO | MinIO or an S3-compatible managed service via the same storage port |
| PostgreSQL | Local container | Managed or self-hosted PostgreSQL |
| Kafka | Local KRaft broker | Managed or self-hosted Kafka; adapters stay Kafka-protocol based |
| Secrets | Local `.env` file only | Secret manager and workload identity, projected as Kubernetes Secrets/files |
| Telemetry | Local Collector, Prometheus, Loki, Grafana | Collector gateway plus managed or self-hosted compatible backends |

## AWS migration boundary

When AWS is selected, add an `infra/terraform/environments/aws` composition that binds these runtime ports to AWS services. Do not alter domain events or use cases. Evaluate S3, RDS for PostgreSQL, MSK, EKS, and an approved secrets/observability offering behind the existing configuration and adapters.

## Worker lifecycle

Each event stage becomes an independently scalable worker deployment. The worker name is supplied as an argument, and its configuration is injected through a ConfigMap and a pre-created Secret. Horizontal scaling must be paired with Kafka consumer-group semantics, idempotency, and per-stage resource sizing. Define liveness/readiness probes when each worker exposes a real health contract; do not add probes that merely test Python process startup.
