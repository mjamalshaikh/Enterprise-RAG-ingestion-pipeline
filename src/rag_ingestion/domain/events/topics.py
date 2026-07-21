"""Kafka topic names for the versioned ingestion event stream."""

TOPIC_PREFIX = "rag.ingestion.v1"

DOCUMENT_SUBMITTED = f"{TOPIC_PREFIX}.document.submitted"
DOCUMENT_FETCHED = f"{TOPIC_PREFIX}.document.fetched"
CONTENT_EXTRACTED = f"{TOPIC_PREFIX}.content.extracted"
CHUNKS_CREATED = f"{TOPIC_PREFIX}.chunks.created"
EMBEDDINGS_GENERATED = f"{TOPIC_PREFIX}.embeddings.generated"
DOCUMENT_INDEXED = f"{TOPIC_PREFIX}.document.indexed"


def retry_topic(stage: str) -> str:
    return f"{TOPIC_PREFIX}.{stage}.retry"


def dead_letter_topic(stage: str) -> str:
    return f"{TOPIC_PREFIX}.{stage}.dlq"
