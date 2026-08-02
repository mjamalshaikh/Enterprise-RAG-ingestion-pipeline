"""Kafka consumer that normalizes fetched PDFs with Docling for downstream chunking."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, BinaryIO, Protocol
from uuid import UUID

import boto3
from botocore.config import Config
from confluent_kafka import Consumer, KafkaError
from opentelemetry import trace
from sqlalchemy import text

from rag_ingestion.config.settings import Settings, get_settings
from rag_ingestion.domain.events import (
    build_content_extracted_event,
    build_content_extraction_rejected_event,
)
from rag_ingestion.domain.events.topics import CONTENT_EXTRACTED, DOCUMENT_FETCHED, dead_letter_topic
from rag_ingestion.infrastructure.avro import AvroSerializer
from rag_ingestion.infrastructure.document_submission import SourceObjectStore, create_engine_from_settings
from rag_ingestion.infrastructure.observability import WorkerTelemetry, record_worker_message


logger = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[3]
CONSUMER_NAME = "content-extractor"
CHUNK_SIZE = 1024 * 1024


class ExtractionError(ValueError):
    """A deterministic, safe-to-report extraction error."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code


@dataclass(frozen=True)
class ExtractionResult:
    normalized: dict[str, Any]
    manifest: dict[str, Any]
    extraction_status: str


class PdfConverter(Protocol):
    """A reusable, non-thread-safe Docling converter instance."""

    def convert(self, path: Path) -> tuple[dict[str, Any], str]: ...

    def warm(self) -> None: ...


class ArtifactStore:
    """Write tenant-scoped derived artifacts; it cannot read source objects."""

    def __init__(self, settings: Settings) -> None:
        scheme = "https" if settings.minio_secure else "http"
        self.bucket = settings.minio_artifact_bucket
        self.client = boto3.client(
            "s3", endpoint_url=f"{scheme}://{settings.minio_endpoint}",
            aws_access_key_id=settings.minio_access_key,
            aws_secret_access_key=settings.minio_secret_key.get_secret_value(),
            region_name="us-east-1", config=Config(s3={"addressing_style": "path"}),
        )

    def put_json(self, *, key: str, value: dict[str, Any]) -> str:
        # JSON objects are deterministic, so retried events replace only the same immutable key.
        body = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        self.client.put_object(Bucket=self.bucket, Key=key, Body=body, ContentType="application/json")
        return f"s3://{self.bucket}/{key}"


def _docling_version() -> str:
    try:
        return version("docling")
    except PackageNotFoundError:
        return "unknown"


def _without_binary(value: Any) -> Any:
    """Keep extraction evidence, but never persist embedded image bytes in JSON."""

    if isinstance(value, dict):
        return {
            str(key): _without_binary(item)
            for key, item in value.items()
            if str(key).lower() not in {"image", "image_data", "data", "binary", "base64", "pixels"}
        }
    if isinstance(value, list):
        return [_without_binary(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _figure_evidence(document: dict[str, Any]) -> list[dict[str, Any]]:
    """Return figure/picture anchors and captions without inventing visual meaning."""

    figures = document.get("pictures", [])
    if not isinstance(figures, list):
        return []
    result: list[dict[str, Any]] = []
    for index, figure in enumerate(figures):
        if not isinstance(figure, dict):
            continue
        result.append(
            {
                "figure_index": index,
                "self_ref": str(figure.get("self_ref", "")),
                "captions": _without_binary(figure.get("captions", [])),
                "provenance": _without_binary(figure.get("prov", [])),
            }
        )
    return result


class DoclingPdfConverter:
    """Own one Docling instance so its models are loaded once per extraction slot."""

    def __init__(self) -> None:
        self._converter: Any | None = None

    def convert(self, path: Path) -> tuple[dict[str, Any], str]:
        """Convert with a lazy, reusable Docling instance."""

        try:
            from docling.document_converter import DocumentConverter

            if self._converter is None:
                self._converter = DocumentConverter()
            converted = self._converter.convert(path)
            document = converted.document
            exported = document.export_to_dict()
            markdown = document.export_to_markdown()
        except ImportError as error:
            raise RuntimeError("Docling is not installed in the worker image.") from error
        except Exception as error:
            raise ExtractionError("docling_conversion_failed", "Docling could not normalize this PDF.") from error
        if not isinstance(exported, dict):
            raise ExtractionError("invalid_docling_output", "Docling did not produce a structured document.")
        return _without_binary(exported), markdown

    def warm(self) -> None:
        """Load the OCR, layout, and table models before the consumer owns a Kafka record."""

        from pypdf import PdfWriter

        with NamedTemporaryFile(suffix=".pdf", delete=False) as temporary:
            path = Path(temporary.name)
            writer = PdfWriter()
            writer.add_blank_page(width=72, height=72)
            writer.write(temporary)
        try:
            self.convert(path)
        finally:
            path.unlink(missing_ok=True)


def _extract_pdf(path: Path) -> tuple[dict[str, Any], str]:
    """Convert one PDF when no worker-owned warmed converter is supplied."""

    return DoclingPdfConverter().convert(path)


def extract_pdf(
    source: BinaryIO, *, max_bytes: int, expected_sha256: str, converter: PdfConverter | None = None
) -> ExtractionResult:
    """Bound input size, normalize a PDF, and retain text/table/figure provenance."""

    total = 0
    digest = hashlib.sha256()
    temporary = NamedTemporaryFile(suffix=".pdf", delete=False)
    temp_path = Path(temporary.name)
    try:
        with temporary:
            while chunk := source.read(CHUNK_SIZE):
                total += len(chunk)
                if total > max_bytes:
                    raise ExtractionError("source_too_large", "Document exceeds the extraction size limit.")
                digest.update(chunk)
                temporary.write(chunk)
            if total == 0:
                raise ExtractionError("empty_source", "Document has no bytes to extract.")
            temporary.flush()
        exported, markdown = converter.convert(temp_path) if converter is not None else _extract_pdf(temp_path)
    finally:
        temp_path.unlink(missing_ok=True)

    exported = _without_binary(exported)
    if digest.hexdigest() != expected_sha256:
        raise ExtractionError("source_checksum_mismatch", "Source bytes do not match the fetched checksum.")
    figures = _figure_evidence(exported)
    tables = exported.get("tables", [])
    text_length = len(markdown.strip())
    quality = {
        "source_bytes": total,
        "text_characters": text_length,
        "table_count": len(tables) if isinstance(tables, list) else 0,
        "figure_count": len(figures),
        "empty_text": text_length == 0,
        "visual_interpretation": "not_performed",
    }
    status = "needs_review" if quality["empty_text"] else "succeeded"
    normalized = {
        "schema_version": "1.0.0",
        "format": "pdf",
        "markdown": markdown,
        "document": exported,
        "figures": figures,
        "visual_interpretation": "not_performed",
    }
    return ExtractionResult(
        normalized=normalized,
        manifest={"extractor": "docling", "extractor_version": _docling_version(), "quality": quality},
        extraction_status=status,
    )


class ContentExtractorRepository:
    """Persist a terminal extraction result and its handoff atomically."""

    def __init__(self, engine: Any) -> None:
        self.engine = engine

    async def complete(
        self, payload: dict[str, Any], result: ExtractionResult, normalized_uri: str, manifest_uri: str
    ) -> bool:
        tenant_id, document_id, version_id, received_event_id = _payload_ids(payload)
        async with self.engine.begin() as connection:
            await connection.execute(text("SELECT set_config('app.tenant_id', :tenant_id, true)"), {"tenant_id": str(tenant_id)})
            claimed = await connection.execute(text("""
                INSERT INTO rag.processed_events (tenant_id, event_id, consumer_name)
                VALUES (:tenant_id, :event_id, :consumer_name) ON CONFLICT DO NOTHING RETURNING event_id
            """), {"tenant_id": tenant_id, "event_id": received_event_id, "consumer_name": CONSUMER_NAME})
            if claimed.scalar_one_or_none() is None:
                return False
            version = (await connection.execute(text("""
                SELECT id FROM rag.document_versions WHERE tenant_id = :tenant_id AND id = :version_id
                  AND document_id = :document_id AND content_sha256 = :content_sha256 AND deleted_at IS NULL
            """), {"tenant_id": tenant_id, "version_id": version_id, "document_id": document_id,
                  "content_sha256": payload["content_sha256"]})).scalar_one_or_none()
            if version is None:
                raise ExtractionError("unknown_document_version", "Fetched event does not identify a current document version.")
            quality = result.manifest["quality"]
            await connection.execute(text("""
                UPDATE rag.document_versions SET normalized_object_uri = :normalized_uri,
                    extraction_manifest_uri = :manifest_uri, extraction_status = :status,
                    extraction_config = CAST(:config AS jsonb), extraction_metadata = CAST(:metadata AS jsonb)
                WHERE tenant_id = :tenant_id AND id = :version_id
            """), {"tenant_id": tenant_id, "version_id": version_id, "normalized_uri": normalized_uri,
                  "manifest_uri": manifest_uri, "status": result.extraction_status,
                  "config": json.dumps({"extractor": "docling", "extractor_version": _docling_version()}),
                  "metadata": json.dumps(quality)})
            await connection.execute(text("UPDATE rag.documents SET status = :status WHERE tenant_id = :tenant_id AND id = :document_id"),
                                     {"tenant_id": tenant_id, "document_id": document_id,
                                      "status": "extracted" if result.extraction_status == "succeeded" else "failed"})
            event_id, event = build_content_extracted_event(
                tenant_id=tenant_id, document_id=document_id, document_version_id=version_id,
                normalized_artifact_uri=normalized_uri, manifest_uri=manifest_uri,
                content_sha256=payload["content_sha256"], extractor_name="docling",
                extractor_version=_docling_version(), extraction_status=result.extraction_status,
                quality_summary=quality, correlation_id=UUID(payload["correlation_id"]), causation_id=received_event_id,
            )
            await connection.execute(text("""
                INSERT INTO rag.ingestion_outbox (tenant_id, event_id, aggregate_type, aggregate_id, event_type,
                    kafka_topic, event_schema_name, payload, headers)
                VALUES (:tenant_id, :event_id, 'document_version', :version_id, 'ContentExtracted', :topic,
                    'content-extracted', CAST(:payload AS jsonb), CAST(:headers AS jsonb))
            """), {"tenant_id": tenant_id, "event_id": event_id, "version_id": version_id,
                  "topic": CONTENT_EXTRACTED, "payload": json.dumps(event),
                  "headers": json.dumps({"event_type": "ContentExtracted", "causation_id": str(received_event_id)})})
            return True

    async def reject(self, payload: dict[str, Any], error: ExtractionError) -> bool:
        tenant_id, document_id, version_id, received_event_id = _payload_ids(payload)
        async with self.engine.begin() as connection:
            await connection.execute(text("SELECT set_config('app.tenant_id', :tenant_id, true)"), {"tenant_id": str(tenant_id)})
            claimed = await connection.execute(text("""
                INSERT INTO rag.processed_events (tenant_id, event_id, consumer_name)
                VALUES (:tenant_id, :event_id, :consumer_name) ON CONFLICT DO NOTHING RETURNING event_id
            """), {"tenant_id": tenant_id, "event_id": received_event_id, "consumer_name": CONSUMER_NAME})
            if claimed.scalar_one_or_none() is None:
                return False
            await connection.execute(text("UPDATE rag.document_versions SET extraction_status = 'failed', extraction_metadata = CAST(:metadata AS jsonb) WHERE tenant_id = :tenant_id AND id = :version_id"),
                                     {"tenant_id": tenant_id, "version_id": version_id, "metadata": json.dumps({"error_code": error.code})})
            await connection.execute(text("UPDATE rag.documents SET status = 'failed' WHERE tenant_id = :tenant_id AND id = :document_id"), {"tenant_id": tenant_id, "document_id": document_id})
            event_id, event = build_content_extraction_rejected_event(tenant_id=tenant_id, document_id=document_id,
                document_version_id=version_id, correlation_id=UUID(payload["correlation_id"]), causation_id=received_event_id, error_code=error.code)
            await connection.execute(text("""
                INSERT INTO rag.ingestion_outbox (tenant_id, event_id, aggregate_type, aggregate_id, event_type,
                    kafka_topic, event_schema_name, payload, headers)
                VALUES (:tenant_id, :event_id, 'document_version', :version_id, 'ContentExtractionRejected', :topic,
                    'content-extraction-rejected', CAST(:payload AS jsonb), CAST(:headers AS jsonb))
            """), {"tenant_id": tenant_id, "event_id": event_id, "version_id": version_id,
                  "topic": dead_letter_topic(CONSUMER_NAME), "payload": json.dumps(event),
                  "headers": json.dumps({"event_type": "ContentExtractionRejected", "causation_id": str(received_event_id)})})
            return True


def _payload_ids(payload: dict[str, Any]) -> tuple[UUID, UUID, UUID, UUID]:
    return (UUID(payload["tenant_id"]), UUID(payload["document_id"]), UUID(payload["document_version_id"]), UUID(payload["event_id"]))


class ContentExtractor:
    """Run extraction outside the DB transaction, then persist the durable handoff."""

    def __init__(
        self,
        source_store: SourceObjectStore,
        artifact_store: ArtifactStore,
        repository: ContentExtractorRepository,
        max_bytes: int,
        converters: list[PdfConverter],
    ) -> None:
        if not converters:
            raise ValueError("At least one document converter is required.")
        self._source_store = source_store
        self._artifact_store = artifact_store
        self._repository = repository
        self._max_bytes = max_bytes
        self._converters: asyncio.Queue[PdfConverter] = asyncio.Queue()
        for converter in converters:
            self._converters.put_nowait(converter)

    async def warm(self) -> None:
        """Warm each bounded extraction slot before Kafka records are consumed."""

        converters: list[PdfConverter] = []
        while not self._converters.empty():
            converter = self._converters.get_nowait()
            converters.append(converter)
            await asyncio.to_thread(converter.warm)
        for converter in converters:
            self._converters.put_nowait(converter)

    async def handle(self, payload: dict[str, Any]) -> bool:
        with trace.get_tracer(__name__).start_as_current_span("rag.content-extractor.process", attributes={"rag.tenant_id": str(payload.get("tenant_id", "")), "rag.document_id": str(payload.get("document_id", "")), "messaging.operation": "process"}):
            try:
                if payload.get("event_type") != "DocumentFetched":
                    raise ExtractionError("unexpected_event_type", "Extractor accepts only DocumentFetched events.")
                if payload.get("inspection_status") != "valid" or payload.get("detected_mime_type") != "application/pdf":
                    raise ExtractionError("unsupported_source", "Only fetch-validated PDFs are supported by this extractor.")
                body = await asyncio.to_thread(self._source_store.get, uri=str(payload["payload_uri"]))
                converter = await self._converters.get()
                try:
                    result = await asyncio.to_thread(
                        extract_pdf, body, max_bytes=self._max_bytes,
                        expected_sha256=str(payload["content_sha256"]), converter=converter,
                    )
                finally:
                    body.close()
                    self._converters.put_nowait(converter)
                tenant_id, _, version_id, _ = _payload_ids(payload)
                prefix = f"{tenant_id}/{version_id}/extracted/{payload['content_sha256']}"
                normalized_uri = await asyncio.to_thread(self._artifact_store.put_json, key=f"{prefix}/normalized.json", value=result.normalized)
                manifest = {**result.manifest, "source_content_sha256": payload["content_sha256"], "extraction_status": result.extraction_status}
                manifest_uri = await asyncio.to_thread(self._artifact_store.put_json, key=f"{prefix}/manifest.json", value=manifest)
                return await self._repository.complete(payload, result, normalized_uri, manifest_uri)
            except ExtractionError as error:
                return await self._repository.reject(payload, error)


def _serializer() -> AvroSerializer:
    return AvroSerializer(json.loads((ROOT / "schemas" / "avro" / "document-fetched.avsc").read_text(encoding="utf-8")))


async def _run() -> None:
    settings = get_settings()
    engine = create_engine_from_settings(settings)
    extractor = ContentExtractor(
        SourceObjectStore(settings),
        ArtifactStore(settings),
        ContentExtractorRepository(engine),
        settings.document_extraction_max_bytes,
        [DoclingPdfConverter() for _ in range(settings.document_extractor_max_concurrency)],
    )
    serializer = _serializer()
    telemetry = WorkerTelemetry(CONSUMER_NAME, "Kafka topic rag.ingestion.v1.document.fetched", logger)
    logger.info(
        "Warming %d Docling extraction slot(s) before consuming Kafka messages.",
        settings.document_extractor_max_concurrency,
    )
    await extractor.warm()
    consumer = Consumer(
        {
            "bootstrap.servers": settings.kafka_bootstrap_servers,
            "group.id": CONSUMER_NAME,
            "enable.auto.commit": False,
            "auto.offset.reset": "earliest",
            "max.poll.interval.ms": settings.document_extractor_max_poll_interval_seconds * 1000,
        }
    )
    consumer.subscribe([DOCUMENT_FETCHED])
    inflight: dict[asyncio.Task[bool], Any] = {}
    paused = False

    async def process(payload: dict[str, Any]) -> bool:
        with telemetry.processing("process"):
            return await extractor.handle(payload)

    try:
        while True:
            completed = [task for task in inflight if task.done()]
            for task in completed:
                message = inflight.pop(task)
                processed = task.result()
                record_worker_message(CONSUMER_NAME, "processed" if processed else "duplicate")
                await asyncio.to_thread(consumer.commit, message=message, asynchronous=False)
            if paused and len(inflight) < settings.document_extractor_max_concurrency:
                partitions = consumer.assignment()
                if partitions:
                    consumer.resume(partitions)
                paused = False

            telemetry.poll_started()
            message = await asyncio.to_thread(consumer.poll, settings.document_extractor_poll_timeout_seconds)
            if message is None:
                telemetry.poll_finished("empty")
                continue
            if message.error():
                if message.error().code() != KafkaError._PARTITION_EOF:
                    telemetry.poll_finished("error")
                    raise RuntimeError(message.error())
                telemetry.poll_finished("partition_eof")
                continue
            telemetry.poll_finished("message")
            inflight[asyncio.create_task(process(serializer.deserialize(message.value())))] = message
            if len(inflight) >= settings.document_extractor_max_concurrency:
                partitions = consumer.assignment()
                if partitions:
                    consumer.pause(partitions)
                    paused = True
    finally:
        for task in inflight:
            task.cancel()
        if inflight:
            await asyncio.gather(*inflight, return_exceptions=True)
        consumer.close()
        await engine.dispose()


def run() -> None:
    """Run the content extractor until the container is stopped."""

    asyncio.run(_run())
