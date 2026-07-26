"""FastAPI entry point for submitting source documents to the pipeline."""

from __future__ import annotations

import hashlib
import logging
from contextlib import asynccontextmanager
from tempfile import SpooledTemporaryFile
from uuid import UUID, uuid4

from fastapi import FastAPI, File, Form, Header, HTTPException, Request, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError

from rag_ingestion.config.settings import Settings, get_settings
from rag_ingestion.domain.events import build_document_submitted_event
from rag_ingestion.infrastructure.document_submission import (
    DocumentSubmissionRepository,
    SourceObjectStore,
    create_engine_from_settings,
    source_object_key,
)
from rag_ingestion.infrastructure.observability import (
    configure_observability,
    shutdown_observability,
)

CHUNK_SIZE = 1024 * 1024
logger = logging.getLogger(__name__)


class SubmissionResponse(BaseModel):
    document_id: UUID
    document_version_id: UUID
    event_id: UUID
    status: str = "submitted"
    source_object_uri: str


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create the HTTP API; settings are injectable to make integration testing simple."""

    settings = settings or get_settings()
    configure_observability(settings)
    engine = create_engine_from_settings(settings)
    repository = DocumentSubmissionRepository(engine)
    object_store = SourceObjectStore(settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        await engine.dispose()
        shutdown_observability()

    app = FastAPI(title="RAG document submission API", version="0.1.0", lifespan=lifespan)

    @app.exception_handler(Exception)
    async def unhandled_exception(_: Request, error: Exception) -> JSONResponse:
        """Record unexpected request failures without exposing details to clients."""

        logger.exception("Unhandled API exception: %s", error)
        return JSONResponse(status_code=500, content={"detail": "Internal server error."})

    @app.get("/healthz", tags=["operations"])
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post(
        "/v1/documents",
        response_model=SubmissionResponse,
        status_code=status.HTTP_201_CREATED,
        tags=["documents"],
        summary="Upload a source document and enqueue DocumentSubmitted",
    )
    async def submit_document(
        file: UploadFile = File(..., description="Document bytes to ingest"),
        x_tenant_id: UUID = Header(..., description="Existing RAG tenant UUID"),
        title: str | None = Form(None),
        classification: str = Form("internal"),
        source_external_id: str | None = Form(None),
    ) -> SubmissionResponse:
        if not file.filename:
            raise HTTPException(status_code=422, detail="A filename is required.")

        # Spooling keeps typical uploads in memory but avoids loading large files
        # entirely into memory while calculating the immutable content digest.
        digest = hashlib.sha256()
        byte_size = 0
        with SpooledTemporaryFile(max_size=8 * CHUNK_SIZE, mode="w+b") as buffered:
            while chunk := await file.read(CHUNK_SIZE):
                digest.update(chunk)
                byte_size += len(chunk)
                buffered.write(chunk)

            document_id, version_id = uuid4(), uuid4()
            external_id = source_external_id or str(document_id)
            key = source_object_key(x_tenant_id, document_id, file.filename)
            mime_type = file.content_type or "application/octet-stream"
            buffered.seek(0)
            try:
                source_uri = await run_in_threadpool(
                    object_store.put,
                    key=key,
                    file=buffered,
                    content_type=mime_type,
                    sha256=digest.hexdigest(),
                )
            except Exception as error:
                # Preserve a safe API response while retaining the MinIO/S3
                # exception and traceback in the local API process logs.
                logger.exception(
                    "Unable to upload submitted document to source storage: %s "
                    "(bucket=%s, key=%s).",
                    error,
                    object_store.bucket,
                    key,
                )
                raise HTTPException(status_code=503, detail="Source object storage is unavailable.") from error

            event_id, event_payload = build_document_submitted_event(
                tenant_id=x_tenant_id, document_id=document_id, payload_uri=source_uri
            )
            try:
                await repository.create_submission(
                    tenant_id=x_tenant_id,
                    document_id=document_id,
                    version_id=version_id,
                    source_external_id=external_id,
                    title=title or file.filename,
                    classification=classification,
                    content_sha256=digest.hexdigest(),
                    source_object_uri=source_uri,
                    mime_type=mime_type,
                    byte_size=byte_size,
                    event_id=event_id,
                    event_payload=event_payload,
                )
            except IntegrityError as error:
                await run_in_threadpool(object_store.delete, key=key)
                logger.exception("Document submission violates an integrity constraint: %s", error)
                raise HTTPException(
                    status_code=409,
                    detail="A document with this source_external_id already exists for the tenant.",
                ) from error
            except Exception as error:
                # Object storage cannot participate in the PostgreSQL transaction.
                # Best-effort compensation prevents an orphan for a failed submit.
                await run_in_threadpool(object_store.delete, key=key)
                logger.exception("Unable to persist submitted document: %s", error)
                raise

        return SubmissionResponse(
            document_id=document_id,
            document_version_id=version_id,
            event_id=event_id,
            source_object_uri=source_uri,
        )

    return app


app = create_app()
