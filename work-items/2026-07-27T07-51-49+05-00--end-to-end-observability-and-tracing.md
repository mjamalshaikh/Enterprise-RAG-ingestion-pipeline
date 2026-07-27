# Work item: End-to-end observability and tracing

- Recorded at: 2026-07-27T07:51:49+05:00
- Status: completed

## Prompt

> we need to implement observability across the repo insuring that during development mode, all the exception details including the exception message are printed on the console but when the environment is production all the errors be sent to open telemetry collector ? please ensure that the environment variable picks the value from the configuration file like host.env or container.env.

> please update the repo to ensure all API's, workers, ... etc use my observability stack and yes please add the provisioning stuff as well.i believe there is no need to update the database ?

> please proceed adding your recommendations.

## Outcome

Implemented a shared observability bootstrap for the API, worker launcher, and
Qdrant bootstrap process. Error logs can be routed to the console or OTLP with
`RAG_OBSERVABILITY_MODE`; tracing is independently controlled by
`RAG_TRACING_ENABLED` and sampling settings.

Added OTLP tracing for FastAPI requests, SQLAlchemy operations, outbound HTTPX
and Botocore calls, and worker/bootstrap spans. The local Docker stack now
provisions Tempo, configures the OpenTelemetry Collector to route traces to it,
and provisions a Tempo datasource in Grafana. Loki receives OTLP logs and
Prometheus continues to scrape collector metrics.

No database schema or migration changes were required because logs, traces, and
metrics are sent to the external observability stack.

## Verification

- Targeted Ruff checks passed.
- API tracing initialization was verified with tracing both enabled and disabled.
- Docker Compose configuration validated successfully.
- Pytest passed.
