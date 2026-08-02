"""Contract builders for content-extractor outcomes."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4


def build_content_extracted_event(
    *, tenant_id: UUID, document_id: UUID, document_version_id: UUID,
    normalized_artifact_uri: str, manifest_uri: str, content_sha256: str,
    extractor_name: str, extractor_version: str, extraction_status: str,
    quality_summary: dict[str, Any], correlation_id: UUID, causation_id: UUID,
) -> tuple[UUID, dict[str, str]]:
    """Build a reference-only handoff for the chunker."""

    event_id = uuid4()
    return event_id, {
        "event_id": str(event_id), "event_type": "ContentExtracted",
        "occurred_at": datetime.now(UTC).isoformat(), "correlation_id": str(correlation_id),
        "causation_id": str(causation_id), "tenant_id": str(tenant_id),
        "document_id": str(document_id), "document_version_id": str(document_version_id),
        "normalized_artifact_uri": normalized_artifact_uri, "manifest_uri": manifest_uri,
        "content_sha256": content_sha256, "extractor_name": extractor_name,
        "extractor_version": extractor_version, "extraction_status": extraction_status,
        "quality_summary": json.dumps(quality_summary, sort_keys=True), "schema_version": "1.0.0",
    }


def build_content_extraction_rejected_event(
    *, tenant_id: UUID, document_id: UUID, document_version_id: UUID,
    correlation_id: UUID, causation_id: UUID, error_code: str,
) -> tuple[UUID, dict[str, str]]:
    """Build a safe DLQ record for deterministic extraction failures."""

    event_id = uuid4()
    return event_id, {
        "event_id": str(event_id), "event_type": "ContentExtractionRejected",
        "occurred_at": datetime.now(UTC).isoformat(), "correlation_id": str(correlation_id),
        "causation_id": str(causation_id), "tenant_id": str(tenant_id),
        "document_id": str(document_id), "document_version_id": str(document_version_id),
        "error_code": error_code, "schema_version": "1.0.0",
    }
