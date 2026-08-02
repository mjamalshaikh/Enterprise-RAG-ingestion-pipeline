from io import BytesIO

import pytest
from pypdf import PdfWriter

from rag_ingestion.workers.document_fetcher import FetchValidationError, inspect_pdf


def test_inspect_pdf_records_detected_type_checksum_size_and_page_count() -> None:
    document = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.write(document)
    content = document.getvalue()

    inspection = inspect_pdf(
        BytesIO(content),
        declared_mime_type="application/pdf",
        max_document_bytes=1_048_576,
    )

    assert inspection.detected_mime_type == "application/pdf"
    assert inspection.byte_size == len(content)
    assert len(inspection.content_sha256) == 64
    assert inspection.metadata["preliminary_page_count"] == 1


def test_inspect_pdf_rejects_non_pdf_content_despite_a_pdf_filename_or_declared_type() -> None:
    with pytest.raises(FetchValidationError, match="PDF signature") as error:
        inspect_pdf(
            BytesIO(b"<html>not a PDF</html>"),
            declared_mime_type="application/pdf",
            max_document_bytes=1_048_576,
        )

    assert error.value.code == "invalid_pdf_signature"


def test_inspect_pdf_rejects_documents_larger_than_the_configured_byte_limit() -> None:
    content = b"%PDF-1.7\n" + (b"x" * 100)

    with pytest.raises(FetchValidationError) as error:
        inspect_pdf(
            BytesIO(content),
            declared_mime_type="application/pdf",
            max_document_bytes=32,
        )

    assert error.value.code == "document_too_large"
    assert error.value.metadata["max_document_bytes"] == 32
