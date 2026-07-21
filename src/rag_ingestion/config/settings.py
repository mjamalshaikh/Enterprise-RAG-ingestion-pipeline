"""Typed configuration for the pipeline's external service adapters."""

from functools import lru_cache

from pydantic import AnyHttpUrl, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Settings loaded from ``RAG_``-prefixed environment variables or a local .env file."""

    model_config = SettingsConfigDict(env_file=".env", env_prefix="RAG_", extra="ignore")

    environment: str = "local"
    postgres_dsn: str
    kafka_bootstrap_servers: str
    apicurio_url: AnyHttpUrl
    minio_endpoint: str
    minio_access_key: str
    minio_secret_key: SecretStr
    minio_secure: bool = True
    minio_source_bucket: str = "rag-source"
    minio_artifact_bucket: str = "rag-artifacts"
    qdrant_url: AnyHttpUrl
    qdrant_api_key: SecretStr
    qdrant_read_only_api_key: SecretStr | None = None
    qdrant_collection: str = "rag_chunks_bge_m3_v1"
    bge_model_name: str = "BAAI/bge-m3"
    embedding_batch_size: int = Field(default=16, ge=1)
    otel_service_name: str = "rag-ingestion"
    otel_exporter_otlp_endpoint: AnyHttpUrl
    otel_traces_sampler: str = "parentbased_traceidratio"
    otel_traces_sampler_arg: float = Field(default=1.0, ge=0.0, le=1.0)


@lru_cache
def get_settings() -> Settings:
    """Return one immutable settings instance per worker process."""

    return Settings()
