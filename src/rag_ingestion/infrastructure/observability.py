"""Environment-aware logging exported through OpenTelemetry in production."""

from __future__ import annotations

import logging

from opentelemetry import _logs
from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.resources import Resource, SERVICE_NAME

from rag_ingestion.config.settings import Settings


class _ExcludeOpenTelemetryRecords(logging.Filter):
    """Avoid recursively exporting diagnostics emitted by the OTEL SDK itself."""

    def filter(self, record: logging.LogRecord) -> bool:
        return not record.name.startswith("opentelemetry")


def configure_observability(settings: Settings) -> None:
    """Configure process logging once from ``RAG_OBSERVABILITY_MODE``.

    ``RAG_OBSERVABILITY_MODE=console`` writes exception messages and tracebacks
    to the process console. ``RAG_OBSERVABILITY_MODE=otlp`` forwards ERROR
    records, including ``exc_info``, to the configured OTLP collector.
    """

    root_logger = logging.getLogger()
    if getattr(root_logger, "_rag_observability_configured", False):
        return

    root_logger.setLevel(logging.INFO)
    if settings.observability_mode == "otlp":
        resource = Resource.create(
            {
                SERVICE_NAME: settings.otel_service_name,
            }
        )
        provider = LoggerProvider(resource=resource)
        provider.add_log_record_processor(
            BatchLogRecordProcessor(
                OTLPLogExporter(
                    endpoint=str(settings.otel_exporter_otlp_endpoint), insecure=True
                )
            )
        )
        _logs.set_logger_provider(provider)
        handler: logging.Handler = LoggingHandler(
            level=logging.ERROR, logger_provider=provider
        )
        # The exporter can emit its own diagnostics through logging.  Sending
        # those back into itself would create a feedback loop during an outage.
        handler.addFilter(_ExcludeOpenTelemetryRecords())
    else:
        handler = logging.StreamHandler()
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
        )

    handler._rag_observability_handler = True  # type: ignore[attr-defined]
    root_logger.addHandler(handler)
    root_logger._rag_observability_configured = True  # type: ignore[attr-defined]


def shutdown_observability() -> None:
    """Flush production logs before the process exits."""

    provider = _logs.get_logger_provider()
    if isinstance(provider, LoggerProvider):
        provider.shutdown()
