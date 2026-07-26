from uuid import UUID

from rag_ingestion.domain.events import build_document_submitted_event


def test_document_submitted_event_is_an_avro_compatible_object_reference() -> None:
    tenant_id = UUID("d68dc681-45f5-4915-a5dc-bfbb2f17e488")
    document_id = UUID("f4bba6ed-2230-48ad-8958-a5d50a02e467")

    event_id, payload = build_document_submitted_event(
        tenant_id=tenant_id,
        document_id=document_id,
        payload_uri="s3://rag-source/d68dc681/document.pdf",
    )

    assert payload["event_id"] == str(event_id)
    assert payload["event_type"] == "DocumentSubmitted"
    assert payload["tenant_id"] == str(tenant_id)
    assert payload["document_id"] == str(document_id)
    assert payload["payload_uri"].startswith("s3://rag-source/")
    assert payload["causation_id"] is None
