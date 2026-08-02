from __future__ import annotations

from io import BytesIO
from uuid import uuid4

import pytest

from rag_ingestion.domain.events.content_extracted import build_content_extracted_event
from rag_ingestion.workers import content_extractor


def test_extract_pdf_preserves_figure_evidence_but_not_embedded_image_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    source = b"%PDF-1.7 test source"
    monkeypatch.setattr(
        content_extractor,
        "_extract_pdf",
        lambda _: (
            {
                "pictures": [
                    {
                        "self_ref": "#/pictures/0",
                        "captions": ["Architecture overview"],
                        "prov": [{"page_no": 1}],
                        "image": b"image-bytes-must-not-be-persisted",
                    }
                ],
                "tables": [{"self_ref": "#/tables/0"}],
            },
            "A document with a figure.",
        ),
    )

    result = content_extractor.extract_pdf(
        BytesIO(source), max_bytes=1024, expected_sha256=content_extractor.hashlib.sha256(source).hexdigest()
    )

    assert result.extraction_status == "succeeded"
    assert result.manifest["quality"]["figure_count"] == 1
    assert result.manifest["quality"]["table_count"] == 1
    assert result.normalized["figures"][0]["captions"] == ["Architecture overview"]
    assert "image" not in result.normalized["document"]["pictures"][0]
    assert result.normalized["visual_interpretation"] == "not_performed"


def test_extract_pdf_rejects_checksum_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(content_extractor, "_extract_pdf", lambda _: ({}, "some text"))

    with pytest.raises(content_extractor.ExtractionError, match="checksum") as error:
        content_extractor.extract_pdf(BytesIO(b"%PDF-1.7"), max_bytes=1024, expected_sha256="0" * 64)

    assert error.value.code == "source_checksum_mismatch"


def test_extract_pdf_uses_the_worker_owned_converter() -> None:
    class Converter:
        def __init__(self) -> None:
            self.called = False

        def convert(self, _: object) -> tuple[dict[str, object], str]:
            self.called = True
            return {}, "warmed converter output"

        def warm(self) -> None:
            pass

    source = b"%PDF-1.7 test source"
    converter = Converter()
    result = content_extractor.extract_pdf(
        BytesIO(source), max_bytes=1024,
        expected_sha256=content_extractor.hashlib.sha256(source).hexdigest(), converter=converter,
    )

    assert converter.called
    assert result.normalized["markdown"] == "warmed converter output"


def test_content_extracted_event_is_reference_only() -> None:
    tenant_id, document_id, version_id, correlation_id, causation_id = (uuid4() for _ in range(5))
    _, event = build_content_extracted_event(
        tenant_id=tenant_id, document_id=document_id, document_version_id=version_id,
        normalized_artifact_uri="s3://rag-artifacts/tenant/version/normalized.json",
        manifest_uri="s3://rag-artifacts/tenant/version/manifest.json", content_sha256="a" * 64,
        extractor_name="docling", extractor_version="2.0", extraction_status="succeeded",
        quality_summary={"figure_count": 1}, correlation_id=correlation_id, causation_id=causation_id,
    )

    assert "markdown" not in event
    assert event["normalized_artifact_uri"].startswith("s3://")
