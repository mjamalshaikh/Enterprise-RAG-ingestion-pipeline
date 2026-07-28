"""PostgreSQL and S3 adapters used by the document-submission API."""

from __future__ import annotations

import json
from typing import BinaryIO
from uuid import UUID

import boto3
from botocore.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from rag_ingestion.config.settings import Settings
from rag_ingestion.domain.events.topics import DOCUMENT_SUBMITTED


class SourceObjectStore:
    """S3-compatible storage for immutable source document bytes."""

    def __init__(self, settings: Settings) -> None:
        scheme = "https" if settings.minio_secure else "http"
        # An API identity is optional, but its key and secret must be selected
        # together. Selecting each field independently can sign requests with
        # the ingestion access key and the API secret (or the reverse), which
        # MinIO reports as a generic 403 response.
        if settings.minio_api_access_key and settings.minio_api_secret_key:
            access_key = settings.minio_api_access_key
            secret_key = settings.minio_api_secret_key
        else:
            access_key = settings.minio_access_key
            secret_key = settings.minio_secret_key
        self.bucket = settings.minio_source_bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=f"{scheme}://{settings.minio_endpoint}",
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key.get_secret_value(),
            region_name="us-east-1",
            config=Config(s3={"addressing_style": "path"}),
        )

    def put(self, *, key: str, file: BinaryIO, content_type: str, sha256: str) -> str:
        self.client.upload_fileobj(
            file,
            self.bucket,
            key,
            ExtraArgs={"ContentType": content_type, "Metadata": {"sha256": sha256}},
        )
        return f"s3://{self.bucket}/{key}"

    def delete(self, *, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)


class DocumentSubmissionRepository:
    """Persists submission metadata and its outbox message atomically."""

    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    async def create_submission(
        self,
        *,
        tenant_id: UUID,
        document_id: UUID,
        version_id: UUID,
        source_external_id: str,
        title: str | None,
        classification: str,
        content_sha256: str,
        source_object_uri: str,
        mime_type: str,
        byte_size: int,
        event_id: UUID,
        event_payload: dict[str, str | None],
    ) -> None:
        async with self.engine.begin() as connection:
            # RLS policy requires this setting for every tenant-owned write.
            await connection.execute(
                text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
                {"tenant_id": str(tenant_id)},
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO rag.documents
                        (id, tenant_id, source_system, source_external_id, title, classification, status)
                    VALUES
                        (:id, :tenant_id, 'api', :source_external_id, :title, :classification, 'submitted')
                    """
                ),
                {
                    "id": document_id,
                    "tenant_id": tenant_id,
                    "source_external_id": source_external_id,
                    "title": title,
                    "classification": classification,
                },
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO rag.document_versions
                        (id, tenant_id, document_id, version_number, content_sha256,
                         source_object_uri, mime_type, byte_size)
                    VALUES
                        (:id, :tenant_id, :document_id, 1, :content_sha256,
                         :source_object_uri, :mime_type, :byte_size)
                    """
                ),
                {
                    "id": version_id,
                    "tenant_id": tenant_id,
                    "document_id": document_id,
                    "content_sha256": content_sha256,
                    "source_object_uri": source_object_uri,
                    "mime_type": mime_type,
                    "byte_size": byte_size,
                },
            )
            await connection.execute(
                text(
                    """
                    UPDATE rag.documents
                    SET current_version_id = :version_id
                    WHERE id = :document_id AND tenant_id = :tenant_id
                    """
                ),
                {"version_id": version_id, "document_id": document_id, "tenant_id": tenant_id},
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO rag.ingestion_outbox
                        (tenant_id, event_id, aggregate_type, aggregate_id, event_type,
                         kafka_topic, event_schema_name, payload, headers)
                    VALUES
                        (:tenant_id, :event_id, 'document', :document_id, 'DocumentSubmitted',
                         :kafka_topic, 'ingestion-event', CAST(:payload AS jsonb),
                         CAST(:headers AS jsonb))
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "event_id": event_id,
                    "document_id": document_id,
                    "kafka_topic": DOCUMENT_SUBMITTED,
                    "payload": json.dumps(event_payload),
                    "headers": '{"event_type":"DocumentSubmitted"}',
                },
            )


def create_engine_from_settings(settings: Settings) -> AsyncEngine:
    """Create the async PostgreSQL engine used by the API process."""

    return create_async_engine(settings.postgres_dsn, pool_pre_ping=True)


def source_object_key(tenant_id: UUID, document_id: UUID, filename: str) -> str:
    """Return a tenant-partitioned immutable source-object key."""

    safe_filename = filename.replace("/", "_").replace("\\", "_") or "upload"
    return f"{tenant_id}/{document_id}/original/{safe_filename}"
