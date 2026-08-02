import json
from uuid import UUID

from rag_ingestion.domain.events import build_document_fetched_event


def test_document_fetched_event_carries_only_an_object_reference_and_inspection_facts() -> None:
    tenant_id = UUID("d68dc681-45f5-4915-a5dc-bfbb2f17e488")
    document_id = UUID("f4bba6ed-2230-48ad-8958-a5d50a02e467")
    version_id = UUID("1c8e99f8-1328-4da0-84d2-335bd985b88a")
    correlation_id = UUID("c67a812e-4f9b-4c04-9a96-a1ee7174ab43")

    event_id, payload = build_document_fetched_event(
        tenant_id=tenant_id,
        document_id=document_id,
        document_version_id=version_id,
        payload_uri="s3://rag-source/d68dc681/f4bba6ed/original/report.pdf",
        detected_mime_type="application/pdf",
        content_sha256="a" * 64,
        byte_size=42,
        inspection_metadata={"preliminary_page_count": 1},
        correlation_id=correlation_id,
        causation_id=UUID("d5c882e3-8cd8-49a2-8e10-2a204277a208"),
    )

    assert payload["event_id"] == str(event_id)
    assert payload["event_type"] == "DocumentFetched"
    assert payload["document_version_id"] == str(version_id)
    assert payload["correlation_id"] == str(correlation_id)
    assert payload["payload_uri"].startswith("s3://rag-source/")
    assert json.loads(payload["inspection_metadata"] or "{}") == {"preliminary_page_count": 1}
