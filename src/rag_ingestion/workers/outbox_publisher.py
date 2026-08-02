"""Transactional outbox publisher using checked-in Avro event contracts."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

from confluent_kafka import Producer
from sqlalchemy import text

from rag_ingestion.config.settings import get_settings
from rag_ingestion.infrastructure.avro import AvroSerializer
from rag_ingestion.infrastructure.document_submission import create_engine_from_settings
from rag_ingestion.infrastructure.observability import WorkerTelemetry, record_outbox_publish


logger = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[3]
EVENT_SCHEMA_FILES = {
    ("rag.ingestion.v1", "document-submitted"): "document-submitted.avsc",
    ("rag.ingestion.v1", "document-fetched"): "document-fetched.avsc",
    ("rag.ingestion.v1", "document-fetch-rejected"): "document-fetch-rejected.avsc",
    ("rag.ingestion.v1", "content-extracted"): "content-extracted.avsc",
    ("rag.ingestion.v1", "content-extraction-rejected"): "content-extraction-rejected.avsc",
}


class OutboxPublisher:
    """Claim, publish, and complete outbox events using DB security boundaries."""

    def __init__(self, producer: Producer) -> None:
        self._producer = producer
        self._serializers: dict[tuple[str, str], AvroSerializer] = {}

    async def publish_batch(
        self, engine: Any, worker_name: str, batch_size: int, telemetry: WorkerTelemetry
    ) -> int:
        async with engine.begin() as connection:
            result = await connection.execute(
                text("SELECT * FROM rag.claim_outbox_events(:worker_name, :batch_size)"),
                {"worker_name": worker_name, "batch_size": batch_size},
            )
            events = [dict(row) for row in result.mappings()]

        for event in events:
            with telemetry.processing("publish"):
                try:
                    await asyncio.to_thread(self._publish_event, event)
                    await self._complete(engine, event["id"], worker_name, succeeded=True)
                    record_outbox_publish("published")
                    logger.info(
                        "Published outbox event %s to Kafka topic '%s'.",
                        event["id"],
                        event["kafka_topic"],
                    )
                except Exception as error:
                    logger.exception("Failed to publish outbox event %s", event["id"])
                    retry_at = datetime.now(UTC) + timedelta(
                        seconds=min(300, 2 ** min(int(event["attempt_count"]), 8))
                    )
                    await self._complete(
                        engine,
                        event["id"],
                        worker_name,
                        succeeded=False,
                        error_message=str(error)[:4000],
                        retry_at=retry_at,
                    )
                    record_outbox_publish("failed")
        if events:
            logger.info("Completed outbox poll: claimed %d event(s).", len(events))
        return len(events)

    def _publish_event(self, event: dict[str, Any]) -> None:
        contract_namespace, schema_name = self._resolve_contract_metadata(event)
        serializer = self._serializer(contract_namespace, schema_name)
        payload = event["payload"]
        if isinstance(payload, str):
            payload = json.loads(payload)
        headers = event["headers"] or {}
        if isinstance(headers, str):
            headers = json.loads(headers)
        kafka_headers = [(key, str(value).encode()) for key, value in headers.items()]
        kafka_headers.extend(
            [
                ("content-type", b"application/vnd.apache.avro.binary"),
                ("event-contract-namespace", contract_namespace.encode()),
                ("event-schema-name", schema_name.encode()),
                ("schema-version", str(payload["schema_version"]).encode()),
            ]
        )
        self._producer.produce(
            event["kafka_topic"],
            key=f"{event['tenant_id']}:{event['aggregate_id']}",
            value=serializer.serialize(payload),
            headers=kafka_headers,
        )
        outstanding = self._producer.flush(10.0)
        if outstanding:
            raise RuntimeError(f"Kafka delivery timed out with {outstanding} message(s) outstanding.")

    @staticmethod
    def _resolve_contract_metadata(event: dict[str, Any]) -> tuple[str, str]:
        contract_namespace = (
            event.get("event_contract_namespace")
            or event.get("schema_group_id")
            or "rag.ingestion.v1"
        )
        schema_name = event.get("event_schema_name") or event.get("schema_artifact_id")
        if not schema_name:
            raise ValueError("Outbox event is missing its checked-in event schema name.")
        return str(contract_namespace), str(schema_name)

    def _serializer(self, contract_namespace: str, schema_name: str) -> AvroSerializer:
        key = (contract_namespace, schema_name)
        if key not in self._serializers:
            schema_file = EVENT_SCHEMA_FILES.get(key)
            if schema_file is None:
                raise ValueError(
                    f"No checked-in schema is configured for {contract_namespace}/{schema_name}."
                )
            schema = json.loads(
                (ROOT / "schemas" / "avro" / schema_file).read_text(encoding="utf-8")
            )
            self._serializers[key] = AvroSerializer(schema)
        return self._serializers[key]

    @staticmethod
    async def _complete(
        engine: Any,
        outbox_id: UUID,
        worker_name: str,
        *,
        succeeded: bool,
        error_message: str | None = None,
        retry_at: datetime | None = None,
    ) -> None:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "SELECT rag.complete_outbox_event("
                    ":outbox_id, :worker_name, :succeeded, :error_message, :retry_at)"
                ),
                {
                    "outbox_id": outbox_id,
                    "worker_name": worker_name,
                    "succeeded": succeeded,
                    "error_message": error_message,
                    "retry_at": retry_at,
                },
            )


async def _run() -> None:
    settings = get_settings()
    engine = create_engine_from_settings(settings)
    publisher = OutboxPublisher(Producer({"bootstrap.servers": settings.kafka_bootstrap_servers}))
    telemetry = WorkerTelemetry(settings.outbox_publisher_name, "transactional outbox", logger)
    logger.info(
        "Outbox publisher is running: worker=%s, kafka=%s, batch_size=%d, poll_interval=%.1fs.",
        settings.outbox_publisher_name,
        settings.kafka_bootstrap_servers,
        settings.outbox_batch_size,
        settings.outbox_poll_interval_seconds,
    )
    try:
        while True:
            telemetry.poll_started()
            try:
                count = await publisher.publish_batch(
                    engine, settings.outbox_publisher_name, settings.outbox_batch_size, telemetry
                )
            except Exception:
                telemetry.poll_finished("error")
                raise
            if count == 0:
                telemetry.poll_finished("empty")
                logger.info(
                    "Transactional outbox is empty; continuing to poll every %.1f seconds.",
                    settings.outbox_poll_interval_seconds,
                )
                await asyncio.sleep(settings.outbox_poll_interval_seconds)
            else:
                telemetry.poll_finished("events")
    finally:
        await engine.dispose()


def run() -> None:
    """Run until the container is stopped."""

    asyncio.run(_run())
