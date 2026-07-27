"""Environment-aware logging exported through OpenTelemetry in production."""

from __future__ import annotations

import logging
from urllib.parse import urlparse

from opentelemetry import _logs, trace
from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.resources import Resource, SERVICE_NAME
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import ALWAYS_OFF, ALWAYS_ON, ParentBased, TraceIdRatioBased

from rag_ingestion.config.settings import Settings


class _ExcludeOpenTelemetryRecords(logging.Filter):
    """Avoid recursively exporting diagnostics emitted by the OTEL SDK itself."""

    def filter(self, record: logging.LogRecord) -> bool:
        return not record.name.startswith("opentelemetry")


def _otlp_grpc_endpoint(settings: Settings) -> str:
    """Translate the configured HTTP-style endpoint into a gRPC target."""

    parsed = urlparse(str(settings.otel_exporter_otlp_endpoint))
    return parsed.netloc or parsed.path


def _trace_sampler(settings: Settings):
    """Build the supported trace sampler from the committed runtime settings."""

    sampler_name = settings.otel_traces_sampler.lower()
    ratio_sampler = TraceIdRatioBased(settings.otel_traces_sampler_arg)
    samplers = {
        "always_on": ALWAYS_ON,
        "always_off": ALWAYS_OFF,
        "traceidratio": ratio_sampler,
        "parentbased_always_on": ParentBased(ALWAYS_ON),
        "parentbased_always_off": ParentBased(ALWAYS_OFF),
        "parentbased_traceidratio": ParentBased(ratio_sampler),
    }
    try:
        return samplers[sampler_name]
    except KeyError as error:
        raise ValueError(f"Unsupported RAG_OTEL_TRACES_SAMPLER: {sampler_name}") from error


def configure_observability(settings: Settings) -> None:
    """Configure process logging once from ``RAG_OBSERVABILITY_MODE``.

    ``RAG_OBSERVABILITY_MODE=console`` writes exception messages and tracebacks
    to the process console. ``RAG_OBSERVABILITY_MODE=otlp`` forwards ERROR
    records, including ``exc_info``, to the configured OTLP collector.
    ``RAG_TRACING_ENABLED`` independently controls trace export to OTLP.
    """

    root_logger = logging.getLogger()
    if getattr(root_logger, "_rag_observability_configured", False):
        return

    root_logger.setLevel(logging.INFO)
    resource = Resource.create({SERVICE_NAME: settings.otel_service_name})
    if settings.observability_mode == "otlp":
        provider = LoggerProvider(resource=resource)
        provider.add_log_record_processor(
            BatchLogRecordProcessor(
                OTLPLogExporter(
                    endpoint=_otlp_grpc_endpoint(settings), insecure=True
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

    if settings.tracing_enabled:
        tracer_provider = TracerProvider(resource=resource, sampler=_trace_sampler(settings))
        tracer_provider.add_span_processor(
            BatchSpanProcessor(
                OTLPSpanExporter(endpoint=_otlp_grpc_endpoint(settings), insecure=True)
            )
        )
        trace.set_tracer_provider(tracer_provider)
        # Instrument outbound adapters once for every API, worker, and
        # bootstrap process that enables tracing.
        from opentelemetry.instrumentation.botocore import BotocoreInstrumentor
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

        BotocoreInstrumentor().instrument()
        HTTPXClientInstrumentor().instrument()

    handler._rag_observability_handler = True  # type: ignore[attr-defined]
    root_logger.addHandler(handler)
    root_logger._rag_observability_configured = True  # type: ignore[attr-defined]


def instrument_fastapi(app, settings: Settings) -> None:
    """Emit one server span per API request when OTLP observability is enabled."""

    if not settings.tracing_enabled or getattr(app, "_rag_traced", False):
        return

    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

    FastAPIInstrumentor.instrument_app(app, excluded_urls="healthz")
    app._rag_traced = True


def instrument_sqlalchemy(engine, settings: Settings) -> None:
    """Emit client spans for PostgreSQL operations performed by an async engine."""

    if not settings.tracing_enabled:
        return

    from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

    SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine)


def shutdown_observability() -> None:
    """Flush production logs before the process exits."""

    provider = _logs.get_logger_provider()
    if isinstance(provider, LoggerProvider):
        provider.shutdown()
    tracer_provider = trace.get_tracer_provider()
    if isinstance(tracer_provider, TracerProvider):
        tracer_provider.shutdown()
