"""Create the tenant-filtered BGE-M3 hybrid-retrieval collection in Qdrant."""

from __future__ import annotations

import logging

from opentelemetry import trace
from qdrant_client import QdrantClient, models

from rag_ingestion.config.settings import get_settings
from rag_ingestion.infrastructure.observability import configure_observability, shutdown_observability

DENSE_VECTOR_NAME = "dense"
SPARSE_VECTOR_NAME = "sparse"
BGE_M3_DENSE_DIMENSIONS = 1024
logger = logging.getLogger(__name__)


def create_payload_indexes(client: QdrantClient, collection_name: str) -> None:
    """Create indexes required for authorization, lifecycle, and provenance filters."""

    fields = {
        "tenant_id": models.PayloadSchemaType.KEYWORD,
        "document_id": models.PayloadSchemaType.KEYWORD,
        "document_version_id": models.PayloadSchemaType.KEYWORD,
        "chunk_id": models.PayloadSchemaType.KEYWORD,
        "source_system": models.PayloadSchemaType.KEYWORD,
        "mime_type": models.PayloadSchemaType.KEYWORD,
        "language_code": models.PayloadSchemaType.KEYWORD,
        "classification": models.PayloadSchemaType.KEYWORD,
        "acl_principals": models.PayloadSchemaType.KEYWORD,
        "is_active": models.PayloadSchemaType.BOOL,
        "indexed_at": models.PayloadSchemaType.DATETIME,
    }
    for field_name, schema in fields.items():
        client.create_payload_index(
            collection_name=collection_name,
            field_name=field_name,
            field_schema=schema,
            wait=True,
        )


def bootstrap() -> None:
    settings = get_settings()
    configure_observability(settings)
    try:
        with trace.get_tracer(__name__).start_as_current_span("rag.bootstrap.qdrant"):
            collection_name = settings.qdrant_collection
            client = QdrantClient(
                url=str(settings.qdrant_url),
                api_key=settings.qdrant_api_key.get_secret_value(),
                timeout=30,
            )

            if not client.collection_exists(collection_name):
                client.create_collection(
                    collection_name=collection_name,
                    vectors_config={
                        DENSE_VECTOR_NAME: models.VectorParams(
                            size=BGE_M3_DENSE_DIMENSIONS,
                            distance=models.Distance.COSINE,
                            on_disk=True,
                        )
                    },
                    sparse_vectors_config={
                        SPARSE_VECTOR_NAME: models.SparseVectorParams(
                            index=models.SparseIndexParams(on_disk=True)
                        )
                    },
                    hnsw_config=models.HnswConfigDiff(m=16, ef_construct=128),
                    optimizers_config=models.OptimizersConfigDiff(indexing_threshold=20_000),
                    on_disk_payload=True,
                )

            create_payload_indexes(client, collection_name)
            print(f"Qdrant collection '{collection_name}' is ready for BGE-M3 hybrid retrieval.")
    except Exception as error:
        logger.exception("Unable to bootstrap the Qdrant collection: %s", error)
        raise
    finally:
        shutdown_observability()


if __name__ == "__main__":
    bootstrap()
