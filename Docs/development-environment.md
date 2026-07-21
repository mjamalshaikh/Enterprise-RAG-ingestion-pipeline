# Development Environment

## Current local baseline

This project is developed using Docker Desktop. The detected client tooling on 2026-07-20 is Docker Engine client `29.2.1` and Docker Compose `v5.1.0`.

The following systems are provided as containers by [the local Compose stack](../deploy/docker/docker-compose.yml). They are development dependencies, not application libraries installed directly on the host:

| System | Container image | Local endpoint | Purpose |
| --- | --- | --- | --- |
| PostgreSQL | `postgres:16-alpine` | `localhost:5432` | Metadata, idempotency, outbox, and Apicurio persistence |
| MinIO | `minio/minio` | API `localhost:9000`, console `localhost:9001` | S3-compatible source and artifact storage |
| Kafka | `apache/kafka:3.9.0` | `localhost:29092` | Event transport for ingestion stages |
| Apicurio Registry | `apicurio/apicurio-registry` | `localhost:6980` | Event schema registry |
| Qdrant | `qdrant/qdrant:v1.13.4` | HTTP `localhost:6333`, gRPC `localhost:6334` | Vector store |
| OpenTelemetry Collector | `otel/opentelemetry-collector-contrib:0.120.0` | OTLP gRPC `localhost:4317`, HTTP `localhost:4318` | Telemetry gateway |
| Prometheus | `prom/prometheus:v3.2.1` | `localhost:9090` | Metrics storage and alert evaluation |
| Loki | `grafana/loki:3.7.0` | `localhost:3100` | Structured log storage |
| Grafana | `grafana/grafana:11.5.2` | `localhost:3000` | Metrics/log exploration and dashboards |

The worker container is defined separately in [docker-compose.workers.yml](../deploy/docker/docker-compose.workers.yml). It is enabled only through the `workers` Compose profile after the corresponding worker module has been implemented.

## Start the local platform

1. Use `config/env/host.env` for Python running directly on your laptop. It uses `localhost` endpoints and has no secrets.
2. Use `config/env/container.env` for workers running inside Docker. It uses service names such as `postgres` and `kafka` and has no secrets.
3. Create the ignored `secrets/local-access.env` from its committed template and populate all local credentials. Add the ignored `secrets/workers/<worker>.env` file for the worker being started.
4. Start backing services:

   ```text
   docker compose -f deploy/docker/docker-compose.yml --env-file config/env/container.env --env-file secrets/local-access.env up -d
   ```

5. Inspect container state:

   ```text
   docker compose -f deploy/docker/docker-compose.yml ps
   ```

6. Start workers when their modules exist:

   ```text
   docker compose -f deploy/docker/docker-compose.yml -f deploy/docker/docker-compose.workers.yml --env-file config/env/container.env --env-file secrets/local-access.env --env-file secrets/workers/document-fetcher.env --profile workers up --build
   ```

## Verify service availability

| Check | Expected result |
| --- | --- |
| `http://localhost:6333` | Qdrant service response |
| `http://localhost:6980/apis/registry/v3` | Apicurio Registry API response |
| `http://localhost:9090/-/ready` | Prometheus readiness response |
| `http://localhost:3100/ready` | Loki readiness response |
| `http://localhost:3000` | Grafana sign-in page |

Kafka, PostgreSQL, and MinIO should be verified through their container health/status rather than an unauthenticated browser request. Use `docker compose ps` and service-specific clients after credentials are configured.

## Development boundaries

- Docker Compose is for local development only. It intentionally uses a single Kafka broker and local persistent volumes.
- The Compose stack does not imply containers are currently running. `docker compose ps` is the authoritative local check.
- The Python interpreter and project dependencies are separate from Docker Desktop. Install Python 3.11+ and the package dependencies when implementing or testing application code locally.
- Never reuse local development template credentials outside a local machine. Production configuration comes from a secret manager or workload identity.

## How application settings are passed

[`Settings`](../src/rag_ingestion/config/settings.py) reads the committed host profile, an optional ignored `.env`, and the ignored `secrets/local-access.env` file. Process environment variables override all files. For example, `postgres_dsn` is populated from `RAG_POSTGRES_DSN` and `embedding_batch_size` from `RAG_EMBEDDING_BATCH_SIZE`. Pydantic validates and converts the values, including booleans, numbers, URLs, and secrets.

Do not edit `settings.py` to change an endpoint. Set an environment variable instead:

```text
RAG_QDRANT_URL=http://localhost:6333
RAG_EMBEDDING_BATCH_SIZE=32
```

The hostname depends on where the Python process runs:

| Process location | PostgreSQL hostname | Kafka hostname | Qdrant hostname |
| --- | --- | --- | --- |
| Laptop Python process | `localhost` | `localhost:29092` | `localhost:6333` |
| Docker Compose worker | `postgres` | `kafka:9092` | `qdrant:6333` |
| Kubernetes worker | Helm/cluster service DNS name | Helm/cluster service DNS name | Helm/cluster service DNS name |

Inside a container, `localhost` means the container itself, not your laptop or another Compose service. That is why the host and container profiles deliberately use different hostnames.
