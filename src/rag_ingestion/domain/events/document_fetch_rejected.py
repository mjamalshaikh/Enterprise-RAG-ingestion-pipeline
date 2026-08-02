"""Contract builder for a deterministic document-fetch failure."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4


def build_document_fetch_rejected_event(
    *,
    tenant_id: UUID,
    document_id: UUID,
    payload_uri: str,
    correlation_id: UUID,
    causation_id: UUID,
    error_code: str,
    inspection_metadata: dict[str, Any] | None = None,
) -> tuple[UUID, dict[str, str]]:
    """Build the DLQ event without leaking source content or implementation details."""

    event_id = uuid4()
    return event_id, {
        "event_id": str(event_id),
        "event_type": "DocumentFetchRejected",
        "occurred_at": datetime.now(UTC).isoformat(),
        "correlation_id": str(correlation_id),
        "causation_id": str(causation_id),
        "tenant_id": str(tenant_id),
        "document_id": str(document_id),
        "payload_uri": payload_uri,
        "inspection_status": "invalid",
        "inspection_metadata": json.dumps(
            {"validation_error": error_code, **(inspection_metadata or {})}, sort_keys=True
        ),
        "schema_version": "1.0.0",
    }
