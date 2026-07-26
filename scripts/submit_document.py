"""Minimal client for the document-submission API."""

from __future__ import annotations

import argparse
import mimetypes
from pathlib import Path

import httpx


def main() -> None:
    parser = argparse.ArgumentParser(description="Submit a document to the RAG ingestion API.")
    parser.add_argument("file", type=Path)
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    parser.add_argument("--classification", default="internal")
    parser.add_argument("--source-external-id")
    args = parser.parse_args()

    mime_type = mimetypes.guess_type(args.file.name)[0] or "application/octet-stream"
    with args.file.open("rb") as document:
        response = httpx.post(
            f"{args.api_url.rstrip('/')}/v1/documents",
            headers={"X-Tenant-Id": args.tenant_id},
            data={
                "title": args.file.name,
                "classification": args.classification,
                **({"source_external_id": args.source_external_id} if args.source_external_id else {}),
            },
            files={"file": (args.file.name, document, mime_type)},
            timeout=60,
        )
    response.raise_for_status()
    print(response.json())


if __name__ == "__main__":
    main()
