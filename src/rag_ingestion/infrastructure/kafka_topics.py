"""Explicit Kafka topic declarations and idempotent administration."""

from __future__ import annotations

from dataclasses import dataclass
from time import sleep

from confluent_kafka import KafkaError, KafkaException
from confluent_kafka.admin import AdminClient, NewTopic

from rag_ingestion.domain.events.topics import (
    CHUNKS_CREATED,
    CONTENT_EXTRACTED,
    DOCUMENT_FETCHED,
    DOCUMENT_INDEXED,
    DOCUMENT_SUBMITTED,
    EMBEDDINGS_GENERATED,
    dead_letter_topic,
    retry_topic,
)


@dataclass(frozen=True)
class TopicSpec:
    """A versioned pipeline topic and its retention policy."""

    name: str
    retention_ms: int

    @property
    def config(self) -> dict[str, str]:
        return {"cleanup.policy": "delete", "retention.ms": str(self.retention_ms)}


EVENT_RETENTION_MS = 7 * 24 * 60 * 60 * 1000
RETRY_RETENTION_MS = 24 * 60 * 60 * 1000
DLQ_RETENTION_MS = 30 * 24 * 60 * 60 * 1000
PIPELINE_STAGES = ("document-fetcher", "content-extractor", "chunker", "embedder", "indexer")


def pipeline_topic_specs() -> tuple[TopicSpec, ...]:
    """Return every topic that must exist before a worker is started."""

    event_topics = (
        DOCUMENT_SUBMITTED,
        DOCUMENT_FETCHED,
        CONTENT_EXTRACTED,
        CHUNKS_CREATED,
        EMBEDDINGS_GENERATED,
        DOCUMENT_INDEXED,
    )
    return tuple(TopicSpec(name, EVENT_RETENTION_MS) for name in event_topics) + tuple(
        TopicSpec(retry_topic(stage), RETRY_RETENTION_MS) for stage in PIPELINE_STAGES
    ) + tuple(TopicSpec(dead_letter_topic(stage), DLQ_RETENTION_MS) for stage in PIPELINE_STAGES)


def ensure_pipeline_topics(
    bootstrap_servers: str,
    *,
    partitions: int,
    replication_factor: int,
    attempts: int = 30,
) -> tuple[str, ...]:
    """Create missing topics and return their names.

    Existing topics are deliberately left untouched: changing partitions or
    retention is an operational change, not a side effect of application boot.
    """

    if partitions < 1 or replication_factor < 1:
        raise ValueError("Kafka partitions and replication factor must both be positive.")
    admin = AdminClient({"bootstrap.servers": bootstrap_servers})
    specs = pipeline_topic_specs()
    for attempt in range(attempts):
        try:
            existing = admin.list_topics(timeout=10).topics
            missing = [spec for spec in specs if spec.name not in existing]
            futures = admin.create_topics(
                [
                    NewTopic(
                        spec.name,
                        num_partitions=partitions,
                        replication_factor=replication_factor,
                        config=spec.config,
                    )
                    for spec in missing
                ]
            )
            for name, future in futures.items():
                try:
                    future.result()
                except KafkaException as error:
                    if error.args[0].code() != KafkaError.TOPIC_ALREADY_EXISTS:
                        raise RuntimeError(f"Unable to create Kafka topic '{name}': {error}") from error
            return tuple(spec.name for spec in specs)
        except KafkaException:
            if attempt == attempts - 1:
                raise
            sleep(2)
    raise RuntimeError("Kafka topic bootstrap unexpectedly exhausted its retry loop.")
