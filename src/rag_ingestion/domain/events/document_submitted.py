"""Contract builder for the event that starts document ingestion."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4


def build_document_submitted_event(
    *,
    tenant_id: UUID,
    document_id: UUID,
    payload_uri: str,
    correlation_id: UUID | None = None,
) -> tuple[UUID, dict[str, str | None]]:
    """Build the Avro-compatible payload consumed by the document-fetcher.

    The document bytes are deliberately never placed on Kafka; workers receive
    the immutable source-object URI instead.
    """

    event_id = uuid4()
    correlation_id = correlation_id or event_id
    return event_id, {
        "event_id": str(event_id),
        "event_type": "DocumentSubmitted",
        "occurred_at": datetime.now(UTC).isoformat(),
        "correlation_id": str(correlation_id),
        "causation_id": None,
        "tenant_id": str(tenant_id),
        "document_id": str(document_id),
        "payload_uri": payload_uri,
        "schema_version": "1.0.0",
    }
