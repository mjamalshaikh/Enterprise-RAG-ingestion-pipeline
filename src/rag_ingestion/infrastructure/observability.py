"""Environment-aware logging exported through OpenTelemetry in production."""

from __future__ import annotations

import logging
import sys
from contextlib import contextmanager
from collections.abc import Iterator
from urllib.parse import urlparse

from opentelemetry import _logs, metrics, trace
from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import ConsoleMetricExporter, PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource, SERVICE_NAME
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
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

    ``RAG_OBSERVABILITY_MODE=console`` writes logs, enabled traces, and metrics
    to process standard output. ``RAG_OBSERVABILITY_MODE=otlp`` sends all
    three signals to the configured OTLP collector. ``console_and_otlp`` keeps
    readable logs on standard output while sending logs, traces, and metrics to
    OTLP. ``RAG_TRACING_ENABLED`` independently controls trace generation.
    """

    root_logger = logging.getLogger()
    if getattr(root_logger, "_rag_observability_configured", False):
        return

    root_logger.setLevel(logging.INFO)
    resource = Resource.create({SERVICE_NAME: settings.otel_service_name})
    sends_to_otlp = settings.observability_mode in {"otlp", "console_and_otlp"}
    writes_to_console = settings.observability_mode in {"console", "console_and_otlp"}
    handlers: list[logging.Handler] = []

    if sends_to_otlp:
        provider = LoggerProvider(resource=resource)
        provider.add_log_record_processor(
            BatchLogRecordProcessor(
                OTLPLogExporter(
                    endpoint=_otlp_grpc_endpoint(settings), insecure=True
                )
            )
        )
        _logs.set_logger_provider(provider)
        otlp_handler: logging.Handler = LoggingHandler(
            level=logging.INFO, logger_provider=provider
        )
        # The exporter can emit its own diagnostics through logging.  Sending
        # those back into itself would create a feedback loop during an outage.
        otlp_handler.addFilter(_ExcludeOpenTelemetryRecords())
        handlers.append(otlp_handler)

    if writes_to_console:
        # Standard output keeps normal development logs out of PowerShell's
        # native-command error stream while still allowing Tee-Object to copy
        # them to a durable local file.
        console_handler = logging.StreamHandler(stream=sys.stdout)
        console_handler.setLevel(logging.DEBUG)
        console_handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
        )
        handlers.append(console_handler)

    metric_exporter = (
        OTLPMetricExporter(endpoint=_otlp_grpc_endpoint(settings), insecure=True)
        if sends_to_otlp
        else ConsoleMetricExporter()
    )
    metric_reader = PeriodicExportingMetricReader(
        metric_exporter,
        export_interval_millis=int(settings.otel_metrics_export_interval_seconds * 1000),
    )
    metrics.set_meter_provider(MeterProvider(resource=resource, metric_readers=[metric_reader]))

    if settings.tracing_enabled:
        tracer_provider = TracerProvider(resource=resource, sampler=_trace_sampler(settings))
        tracer_provider.add_span_processor(
            BatchSpanProcessor(
                OTLPSpanExporter(endpoint=_otlp_grpc_endpoint(settings), insecure=True)
                if sends_to_otlp
                else ConsoleSpanExporter()
            )
        )
        trace.set_tracer_provider(tracer_provider)
        # Instrument outbound adapters once for every API, worker, and
        # bootstrap process that enables tracing.
        from opentelemetry.instrumentation.botocore import BotocoreInstrumentor
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

        BotocoreInstrumentor().instrument()
        HTTPXClientInstrumentor().instrument()

    for handler in handlers:
        handler._rag_observability_handler = True  # type: ignore[attr-defined]
        root_logger.addHandler(handler)
    root_logger._rag_observability_configured = True  # type: ignore[attr-defined]


def record_worker_message(worker_name: str, outcome: str) -> None:
    """Count one Kafka message outcome with low-cardinality worker labels."""

    metrics.get_meter("rag.ingestion").create_counter(
        "rag.ingestion.worker.messages", unit="{message}", description="Kafka worker message outcomes."
    ).add(1, {"worker.name": worker_name, "outcome": outcome})


def record_worker_poll(worker_name: str, source: str, outcome: str) -> None:
    """Count a worker poll with bounded labels suitable for Prometheus."""

    metrics.get_meter("rag.ingestion").create_counter(
        "rag.ingestion.worker.polls", unit="{poll}", description="Worker polling outcomes."
    ).add(1, {"worker.name": worker_name, "source": source, "outcome": outcome})


class WorkerTelemetry:
    """Standard logs, metrics, and processing spans for polling workers.

    Polling itself is logged and counted on every attempt. Processing spans are
    intentionally reserved for actual messages/events so idle workers do not
    generate high-volume, low-value trace data.
    """

    def __init__(self, worker_name: str, source: str, logger: logging.Logger) -> None:
        self.worker_name = worker_name
        self.source = source
        self.logger = logger

    def poll_started(self) -> None:
        """Record and announce a polling attempt."""

        self.logger.info("Polling %s.", self.source)
        record_worker_poll(self.worker_name, self.source, "started")

    def poll_finished(self, outcome: str) -> None:
        """Record the final polling outcome using a bounded outcome label."""

        record_worker_poll(self.worker_name, self.source, outcome)

    @contextmanager
    def processing(self, operation: str) -> Iterator[None]:
        """Create a trace span for processing a received work item."""

        with trace.get_tracer(__name__).start_as_current_span(
            "rag.worker.process",
            attributes={
                "rag.worker.name": self.worker_name,
                "messaging.operation": operation,
                "messaging.system": self.source,
            },
        ):
            yield


def record_outbox_publish(outcome: str) -> None:
    """Count transactional-outbox delivery outcomes."""

    metrics.get_meter("rag.ingestion").create_counter(
        "rag.ingestion.outbox.publishes", unit="{event}", description="Transactional outbox delivery outcomes."
    ).add(1, {"outcome": outcome})


def record_http_request(method: str, status_code: int) -> None:
    """Count API responses without high-cardinality request-path labels."""

    metrics.get_meter("rag.ingestion").create_counter(
        "rag.ingestion.http.requests", unit="{request}", description="API response outcomes."
    ).add(1, {"http.request.method": method, "http.response.status_code": status_code})


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
    meter_provider = metrics.get_meter_provider()
    if isinstance(meter_provider, MeterProvider):
        meter_provider.shutdown()
