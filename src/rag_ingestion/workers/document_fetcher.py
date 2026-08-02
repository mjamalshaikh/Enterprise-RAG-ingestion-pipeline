"""Kafka consumer that validates submitted source objects and emits DocumentFetched."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from tempfile import SpooledTemporaryFile
from typing import Any, BinaryIO
from uuid import UUID

from confluent_kafka import Consumer, KafkaError
from opentelemetry import trace
from pypdf import PdfReader
from pypdf.errors import PdfReadError
from sqlalchemy import text

from rag_ingestion.config.settings import get_settings
from rag_ingestion.domain.events import (
    build_document_fetch_rejected_event,
    build_document_fetched_event,
)
from rag_ingestion.domain.events.topics import DOCUMENT_FETCHED, DOCUMENT_SUBMITTED, dead_letter_topic
from rag_ingestion.infrastructure.avro import AvroSerializer
from rag_ingestion.infrastructure.document_submission import (
    SourceObjectStore,
    create_engine_from_settings,
)
from rag_ingestion.infrastructure.observability import WorkerTelemetry, record_worker_message


logger = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[3]
CONSUMER_NAME = "document-fetcher"
CHUNK_SIZE = 1024 * 1024


class FetchValidationError(ValueError):
    """A deterministic source-object problem that must not be retried."""

    def __init__(self, code: str, detail: str, *, metadata: dict[str, Any] | None = None) -> None:
        super().__init__(detail)
        self.code = code
        self.metadata = metadata or {}


@dataclass(frozen=True)
class SourceInspection:
    detected_mime_type: str
    content_sha256: str
    byte_size: int
    metadata: dict[str, Any]


def inspect_pdf(
    source: BinaryIO,
    *,
    declared_mime_type: str | None,
    max_document_bytes: int,
) -> SourceInspection:
    """Stream, checksum, and perform a lightweight structural PDF inspection."""

    if declared_mime_type and declared_mime_type not in {"application/pdf", "application/octet-stream"}:
        raise FetchValidationError(
            "declared_mime_type_mismatch",
            "The submitted MIME type is not permitted by the PDF-first fetcher.",
        )
    digest = hashlib.sha256()
    byte_size = 0
    with SpooledTemporaryFile(max_size=8 * CHUNK_SIZE, mode="w+b") as buffered:
        first_chunk = source.read(min(CHUNK_SIZE, max_document_bytes + 1))
        if not first_chunk.startswith(b"%PDF-"):
            raise FetchValidationError("invalid_pdf_signature", "Object does not start with a PDF signature.")
        while first_chunk:
            if byte_size + len(first_chunk) > max_document_bytes:
                raise FetchValidationError(
                    "document_too_large",
                    "PDF exceeds the configured document byte limit.",
                    metadata={
                        "max_document_bytes": max_document_bytes,
                        "observed_bytes_at_rejection": byte_size + len(first_chunk),
                    },
                )
            digest.update(first_chunk)
            byte_size += len(first_chunk)
            buffered.write(first_chunk)
            remaining_bytes = max_document_bytes - byte_size
            first_chunk = source.read(min(CHUNK_SIZE, remaining_bytes + 1))

        buffered.seek(0)
        try:
            reader = PdfReader(buffered, strict=False)
            if reader.is_encrypted:
                raise FetchValidationError(
                    "encrypted_pdf_unsupported", "Encrypted PDFs are not supported by this pipeline."
                )
            page_count = len(reader.pages)
        except FetchValidationError:
            raise
        except (PdfReadError, OSError, ValueError, EOFError) as error:
            raise FetchValidationError("corrupt_pdf", "PDF could not be read by the PDF inspector.") from error

    return SourceInspection(
        detected_mime_type="application/pdf",
        content_sha256=digest.hexdigest(),
        byte_size=byte_size,
        metadata={
            "declared_mime_type": declared_mime_type,
            "detected_mime_type": "application/pdf",
            "format": "pdf",
            "preliminary_page_count": page_count,
            "max_document_bytes": max_document_bytes,
            "is_encrypted": False,
        },
    )


class DocumentFetcherRepository:
    """Persist one fetch result and its outbox handoff in a tenant-scoped transaction."""

    def __init__(self, engine: Any) -> None:
        self.engine = engine

    async def process(
        self, payload: dict[str, Any], inspection: SourceInspection | None, error: FetchValidationError | None
    ) -> bool:
        tenant_id = UUID(payload["tenant_id"])
        document_id = UUID(payload["document_id"])
        received_event_id = UUID(payload["event_id"])
        source_uri = str(payload["payload_uri"])
        async with self.engine.begin() as connection:
            await connection.execute(
                text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
                {"tenant_id": str(tenant_id)},
            )
            claimed = await connection.execute(
                text(
                    """
                    INSERT INTO rag.processed_events (tenant_id, event_id, consumer_name)
                    VALUES (:tenant_id, :event_id, :consumer_name)
                    ON CONFLICT DO NOTHING
                    RETURNING event_id
                    """
                ),
                {"tenant_id": tenant_id, "event_id": received_event_id, "consumer_name": CONSUMER_NAME},
            )
            if claimed.scalar_one_or_none() is None:
                return False

            version_result = await connection.execute(
                text(
                    """
                    SELECT id, mime_type, content_sha256, byte_size
                    FROM rag.document_versions
                    WHERE tenant_id = :tenant_id AND document_id = :document_id
                      AND source_object_uri = :source_uri AND deleted_at IS NULL
                    """
                ),
                {"tenant_id": tenant_id, "document_id": document_id, "source_uri": source_uri},
            )
            version = version_result.mappings().one_or_none()
            if version is None:
                await self._enqueue_failure(
                    connection,
                    payload,
                    FetchValidationError(
                        "unknown_source_object", "Submitted object is not a current document version."
                    ),
                )
                return True

            version_id = UUID(str(version["id"]))
            if inspection is not None and inspection.content_sha256 != version["content_sha256"]:
                error = FetchValidationError(
                    "source_checksum_mismatch", "Stored object differs from submitted version."
                )
            if (
                error is None
                and version["mime_type"] not in {"application/pdf", "application/octet-stream"}
            ):
                error = FetchValidationError(
                    "declared_mime_type_mismatch",
                    "The submitted MIME type is not permitted by the PDF-first fetcher.",
                )
            if error is not None:
                metadata = {"validation_error": error.code, "message": str(error), **error.metadata}
                await connection.execute(
                    text(
                        """
                        UPDATE rag.document_versions
                        SET inspection_status = 'invalid', inspection_metadata = CAST(:metadata AS jsonb)
                        WHERE tenant_id = :tenant_id AND id = :version_id
                        """
                    ),
                    {"tenant_id": tenant_id, "version_id": version_id, "metadata": json.dumps(metadata)},
                )
                await connection.execute(
                    text("UPDATE rag.documents SET status = 'failed' WHERE tenant_id = :tenant_id AND id = :document_id"),
                    {"tenant_id": tenant_id, "document_id": document_id},
                )
                await connection.execute(
                    text(
                        """
                        INSERT INTO rag.ingestion_failures
                            (tenant_id, document_version_id, event_id, stage, error_class, error_code, error_detail)
                        VALUES (:tenant_id, :version_id, :event_id, 'document-fetcher',
                                'validation', :error_code, CAST(:error_detail AS jsonb))
                        """
                    ),
                    {
                        "tenant_id": tenant_id,
                        "version_id": version_id,
                        "event_id": received_event_id,
                        "error_code": error.code,
                        "error_detail": json.dumps(metadata),
                    },
                )
                await self._enqueue_failure(connection, payload, error)
                return True

            assert inspection is not None
            metadata = dict(inspection.metadata)
            metadata["declared_mime_type"] = version["mime_type"]
            await connection.execute(
                text(
                    """
                    UPDATE rag.document_versions
                    SET detected_mime_type = :detected_mime_type, inspection_status = 'valid',
                        inspection_metadata = CAST(:metadata AS jsonb)
                    WHERE tenant_id = :tenant_id AND id = :version_id
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "version_id": version_id,
                    "detected_mime_type": inspection.detected_mime_type,
                    "metadata": json.dumps(metadata),
                },
            )
            await connection.execute(
                text("UPDATE rag.documents SET status = 'fetched' WHERE tenant_id = :tenant_id AND id = :document_id"),
                {"tenant_id": tenant_id, "document_id": document_id},
            )
            fetched_event_id, fetched_payload = build_document_fetched_event(
                tenant_id=tenant_id,
                document_id=document_id,
                document_version_id=version_id,
                payload_uri=source_uri,
                detected_mime_type=inspection.detected_mime_type,
                content_sha256=inspection.content_sha256,
                byte_size=inspection.byte_size,
                inspection_metadata=metadata,
                correlation_id=UUID(payload["correlation_id"]),
                causation_id=received_event_id,
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO rag.ingestion_outbox
                        (tenant_id, event_id, aggregate_type, aggregate_id, event_type,
                         kafka_topic, event_schema_name, payload, headers)
                    VALUES (:tenant_id, :event_id, 'document_version', :aggregate_id, 'DocumentFetched',
                            :topic, 'document-fetched', CAST(:payload AS jsonb), CAST(:headers AS jsonb))
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "event_id": fetched_event_id,
                    "aggregate_id": version_id,
                    "topic": DOCUMENT_FETCHED,
                    "payload": json.dumps(fetched_payload),
                    "headers": json.dumps({"event_type": "DocumentFetched", "causation_id": str(received_event_id)}),
                },
            )
            return True

    @staticmethod
    async def _enqueue_failure(connection: Any, payload: dict[str, Any], error: FetchValidationError) -> None:
        failure_event_id, failure_payload = build_document_fetch_rejected_event(
            tenant_id=UUID(payload["tenant_id"]),
            document_id=UUID(payload["document_id"]),
            payload_uri=str(payload["payload_uri"]),
            correlation_id=UUID(payload["correlation_id"]),
            causation_id=UUID(payload["event_id"]),
            error_code=error.code,
            inspection_metadata=error.metadata,
        )
        await connection.execute(
            text(
                """
                INSERT INTO rag.ingestion_outbox
                    (tenant_id, event_id, aggregate_type, aggregate_id, event_type, kafka_topic,
                     event_schema_name, payload, headers)
                VALUES (:tenant_id, :event_id, 'document', :document_id, 'DocumentFetchRejected', :topic,
                        'document-fetch-rejected', CAST(:payload AS jsonb), CAST(:headers AS jsonb))
                """
            ),
            {
                "tenant_id": UUID(payload["tenant_id"]),
                "event_id": failure_event_id,
                "document_id": UUID(payload["document_id"]),
                "topic": dead_letter_topic(CONSUMER_NAME),
                "payload": json.dumps(failure_payload),
                "headers": json.dumps(
                    {
                        "event_type": "DocumentFetchRejected",
                        "causation_id": str(payload["event_id"]),
                    }
                ),
            },
        )


class DocumentFetcher:
    """Run fetch-stage inspection for one deserialized DocumentSubmitted event."""

    def __init__(
        self,
        object_store: SourceObjectStore,
        repository: DocumentFetcherRepository,
        *,
        max_document_bytes: int,
    ) -> None:
        self._object_store = object_store
        self._repository = repository
        self._max_document_bytes = max_document_bytes

    async def handle(self, payload: dict[str, Any]) -> bool:
        with trace.get_tracer(__name__).start_as_current_span(
            "rag.document-fetcher.process",
            attributes={
                "rag.tenant_id": str(payload.get("tenant_id", "")),
                "rag.document_id": str(payload.get("document_id", "")),
                "messaging.operation": "process",
            },
        ):
            if payload.get("event_type") != "DocumentSubmitted":
                return await self._repository.process(
                    payload,
                    inspection=None,
                    error=FetchValidationError(
                        "unexpected_event_type", "Fetcher accepts only DocumentSubmitted events."
                    ),
                )
            body = None
            try:
                body = await asyncio.to_thread(self._object_store.get, uri=str(payload["payload_uri"]))
                inspection = await asyncio.to_thread(
                    inspect_pdf,
                    body,
                    declared_mime_type=None,
                    max_document_bytes=self._max_document_bytes,
                )
            except FetchValidationError as error:
                return await self._repository.process(payload, inspection=None, error=error)
            finally:
                if body is not None:
                    body.close()
            return await self._repository.process(payload, inspection=inspection, error=None)


def _serializer() -> AvroSerializer:
    schema = json.loads((ROOT / "schemas" / "avro" / "document-submitted.avsc").read_text(encoding="utf-8"))
    return AvroSerializer(schema)


async def _run() -> None:
    settings = get_settings()
    engine = create_engine_from_settings(settings)
    fetcher = DocumentFetcher(
        SourceObjectStore(settings),
        DocumentFetcherRepository(engine),
        max_document_bytes=settings.document_fetcher_max_document_bytes,
    )
    consumer = Consumer(
        {
            "bootstrap.servers": settings.kafka_bootstrap_servers,
            "group.id": CONSUMER_NAME,
            "enable.auto.commit": False,
            "auto.offset.reset": "earliest",
        }
    )
    consumer.subscribe([DOCUMENT_SUBMITTED])
    serializer = _serializer()
    telemetry = WorkerTelemetry(CONSUMER_NAME, "Kafka topic rag.ingestion.v1.document.submitted", logger)
    try:
        while True:
            telemetry.poll_started()
            try:
                message = await asyncio.to_thread(
                    consumer.poll, settings.document_fetcher_poll_timeout_seconds
                )
            except Exception:
                telemetry.poll_finished("error")
                raise
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
            payload = serializer.deserialize(message.value())
            with telemetry.processing("process"):
                processed = await fetcher.handle(payload)
            outcome = "processed" if processed else "duplicate"
            record_worker_message(CONSUMER_NAME, outcome)
            logger.info("Document fetcher completed Kafka message with outcome=%s", outcome)
            await asyncio.to_thread(consumer.commit, message=message, asynchronous=False)
    finally:
        consumer.close()
        await engine.dispose()


def run() -> None:
    """Run the document fetcher until the container is stopped."""

    asyncio.run(_run())
