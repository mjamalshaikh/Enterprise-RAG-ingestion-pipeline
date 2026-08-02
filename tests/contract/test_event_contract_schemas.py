import json
from pathlib import Path
from uuid import UUID

from rag_ingestion.domain.events import (
    build_content_extracted_event,
    build_document_fetch_rejected_event,
    build_document_fetched_event,
    build_document_submitted_event,
)
from rag_ingestion.infrastructure.avro import AvroSerializer
from rag_ingestion.workers.outbox_publisher import OutboxPublisher


ROOT = Path(__file__).resolve().parents[2]


def _serializer(schema_name: str) -> AvroSerializer:
    schema = json.loads((ROOT / "schemas" / "avro" / schema_name).read_text(encoding="utf-8"))
    return AvroSerializer(schema)


def test_document_submitted_has_a_dedicated_contract() -> None:
    event_id, payload = build_document_submitted_event(
        tenant_id=UUID("d68dc681-45f5-4915-a5dc-bfbb2f17e488"),
        document_id=UUID("f4bba6ed-2230-48ad-8958-a5d50a02e467"),
        payload_uri="s3://rag-source/tenant/document/original/report.pdf",
    )

    decoded = _serializer("document-submitted.avsc").deserialize(
        _serializer("document-submitted.avsc").serialize(payload)
    )

    assert decoded["event_id"] == str(event_id)
    assert set(decoded) == {
        "event_id",
        "event_type",
        "occurred_at",
        "correlation_id",
        "causation_id",
        "tenant_id",
        "document_id",
        "payload_uri",
        "schema_version",
    }


def test_document_fetched_and_rejected_contracts_are_independent() -> None:
    tenant_id = UUID("d68dc681-45f5-4915-a5dc-bfbb2f17e488")
    document_id = UUID("f4bba6ed-2230-48ad-8958-a5d50a02e467")
    version_id = UUID("1c8e99f8-1328-4da0-84d2-335bd985b88a")
    correlation_id = UUID("c67a812e-4f9b-4c04-9a96-a1ee7174ab43")
    causation_id = UUID("d5c882e3-8cd8-49a2-8e10-2a204277a208")
    _, fetched = build_document_fetched_event(
        tenant_id=tenant_id,
        document_id=document_id,
        document_version_id=version_id,
        payload_uri="s3://rag-source/tenant/document/original/report.pdf",
        detected_mime_type="application/pdf",
        content_sha256="a" * 64,
        byte_size=42,
        inspection_metadata={"preliminary_page_count": 1},
        correlation_id=correlation_id,
        causation_id=causation_id,
    )
    _, rejected = build_document_fetch_rejected_event(
        tenant_id=tenant_id,
        document_id=document_id,
        payload_uri="s3://rag-source/tenant/document/original/report.pdf",
        correlation_id=correlation_id,
        causation_id=causation_id,
        error_code="corrupt_pdf",
    )

    fetched_decoded = _serializer("document-fetched.avsc").deserialize(
        _serializer("document-fetched.avsc").serialize(fetched)
    )
    rejected_decoded = _serializer("document-fetch-rejected.avsc").deserialize(
        _serializer("document-fetch-rejected.avsc").serialize(rejected)
    )

    assert fetched_decoded["document_version_id"] == str(version_id)
    assert fetched_decoded["byte_size"] == 42
    assert "document_version_id" not in rejected_decoded
    assert rejected_decoded["event_type"] == "DocumentFetchRejected"


def test_outbox_publisher_resolves_only_registered_event_contracts() -> None:
    publisher = OutboxPublisher(None)  # type: ignore[arg-type]

    assert publisher._serializer("rag.ingestion.v1", "document-submitted")
    assert publisher._serializer("rag.ingestion.v1", "document-fetched")
    assert publisher._serializer("rag.ingestion.v1", "content-extracted")


def test_content_extracted_contract_carries_only_artifact_references() -> None:
    tenant_id = UUID("d68dc681-45f5-4915-a5dc-bfbb2f17e488")
    document_id = UUID("f4bba6ed-2230-48ad-8958-a5d50a02e467")
    version_id = UUID("1c8e99f8-1328-4da0-84d2-335bd985b88a")
    correlation_id = UUID("c67a812e-4f9b-4c04-9a96-a1ee7174ab43")
    causation_id = UUID("d5c882e3-8cd8-49a2-8e10-2a204277a208")
    _, payload = build_content_extracted_event(
        tenant_id=tenant_id, document_id=document_id, document_version_id=version_id,
        normalized_artifact_uri="s3://rag-artifacts/tenant/version/normalized.json",
        manifest_uri="s3://rag-artifacts/tenant/version/manifest.json", content_sha256="a" * 64,
        extractor_name="docling", extractor_version="2.0", extraction_status="succeeded",
        quality_summary={"figure_count": 1}, correlation_id=correlation_id, causation_id=causation_id,
    )

    decoded = _serializer("content-extracted.avsc").deserialize(
        _serializer("content-extracted.avsc").serialize(payload)
    )

    assert decoded["normalized_artifact_uri"].startswith("s3://")
    assert "markdown" not in decoded
