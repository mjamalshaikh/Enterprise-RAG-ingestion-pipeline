"""Contract builder for a source object that passed fetch-stage inspection."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4


def build_document_fetched_event(
    *,
    tenant_id: UUID,
    document_id: UUID,
    document_version_id: UUID,
    payload_uri: str,
    detected_mime_type: str,
    content_sha256: str,
    byte_size: int,
    inspection_metadata: dict[str, Any],
    correlation_id: UUID,
    causation_id: UUID,
) -> tuple[UUID, dict[str, Any]]:
    """Build the event consumed by the content extractor.

    The source object remains in MinIO.  Kafka carries only its reference and
    inspection facts, never document bytes or document text.
    """

    event_id = uuid4()
    return event_id, {
        "event_id": str(event_id),
        "event_type": "DocumentFetched",
        "occurred_at": datetime.now(UTC).isoformat(),
        "correlation_id": str(correlation_id),
        "causation_id": str(causation_id),
        "tenant_id": str(tenant_id),
        "document_id": str(document_id),
        "document_version_id": str(document_version_id),
        "payload_uri": payload_uri,
        "detected_mime_type": detected_mime_type,
        "content_sha256": content_sha256,
        "byte_size": byte_size,
        "inspection_status": "valid",
        "inspection_metadata": json.dumps(inspection_metadata, sort_keys=True),
        "schema_version": "1.0.0",
    }
