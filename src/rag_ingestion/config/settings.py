"""Typed configuration for the pipeline's external service adapters."""

from functools import lru_cache
from os import getenv
from pathlib import Path
from re import fullmatch
from typing import Literal

from pydantic import AliasChoices, AnyHttpUrl, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings with Docker Desktop host defaults and environment overrides.

    These defaults target the reviewed, externally-managed Docker Desktop
    stacks when Python runs directly on the host. Containerized workers must
    use their network-local endpoints from their environment file instead.
    """

    model_config = SettingsConfigDict(
        # Profiles contain endpoints only. The final ignored file contains
        # local credentials, including MinIO service identities. An optional
        # .env supports per-developer non-secret overrides. Process variables
        # remain the highest-priority runtime override.
        env_file=("config/env/host.env", ".env", "secrets/local-runtime-secrets.env"),
        env_prefix="RAG_",
        extra="ignore",
    )

    postgres_dsn: str = Field(
        validation_alias=AliasChoices("RAG_POSTGRES_DSN", "POSTGRES_DSN", "postgres_dsn")
    )
    kafka_bootstrap_servers: str = "localhost:29092"
    kafka_topic_partitions: int = Field(default=1, ge=1)
    kafka_topic_replication_factor: int = Field(default=1, ge=1)
    outbox_publisher_name: str = "outbox-publisher"
    outbox_batch_size: int = Field(default=50, ge=1, le=1000)
    outbox_poll_interval_seconds: float = Field(default=1.0, gt=0.0, le=600.0)
    document_fetcher_poll_timeout_seconds: float = Field(default=5.0, gt=0.0, le=600.0)
    document_fetcher_max_document_bytes: int = Field(default=52_428_800, ge=1_048_576)
    api_max_upload_bytes: int = Field(default=52_428_800, ge=1_048_576)
    document_extractor_poll_timeout_seconds: float = Field(default=5.0, gt=0.0, le=600.0)
    document_extraction_max_bytes: int = Field(default=268_435_456, ge=1_048_576)
    document_extractor_max_concurrency: int = Field(default=1, ge=1, le=8)
    document_extractor_max_poll_interval_seconds: int = Field(default=3600, ge=300, le=86_400)
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str
    minio_secret_key: SecretStr
    minio_ingestion_access_key: str | None = None
    minio_ingestion_secret_key: SecretStr | None = None
    minio_api_access_key: str | None = None
    minio_api_secret_key: SecretStr | None = None
    minio_secure: bool = False
    minio_source_bucket: str = "rag-source"
    minio_artifact_bucket: str = "rag-artifacts"
    qdrant_url: AnyHttpUrl = "http://localhost:6333"
    # QDRANT_* names are the canonical secrets used to configure the Qdrant
    # server. RAG_QDRANT_* names are injected into application containers by
    # their worker profiles. Accept either form so host processes can read the
    # local secret file without duplicating the same key under two names.
    qdrant_api_key: SecretStr = Field(
        validation_alias=AliasChoices("RAG_QDRANT_API_KEY", "QDRANT_ADMIN_API_KEY")
    )
    qdrant_read_only_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "RAG_QDRANT_READ_ONLY_API_KEY", "QDRANT_READ_ONLY_API_KEY"
        ),
    )
    qdrant_collection: str = "rag_chunks_bge_m3_v1"
    bge_model_name: str = "BAAI/bge-m3"
    embedding_batch_size: int = Field(default=16, ge=1)
    otel_service_name: str = "rag-ingestion"
    observability_mode: Literal["console", "otlp", "console_and_otlp"] = "console"
    tracing_enabled: bool = False
    otel_metrics_export_interval_seconds: float = Field(default=15.0, gt=0.0, le=300.0)
    otel_exporter_otlp_endpoint: AnyHttpUrl = "http://localhost:4317"
    otel_traces_sampler: str = "parentbased_traceidratio"
    otel_traces_sampler_arg: float = Field(default=1.0, ge=0.0, le=1.0)
    # Keycloak is available locally but the ``rag`` realm is not provisioned
    # by this repository, so enable OIDC only through an explicit URL.
    oidc_issuer_url: AnyHttpUrl | None = None


def _environment_files(worker_name: str | None = None) -> tuple[Path, ...]:
    """Return base, optional worker, and local-secret configuration files.

    Host execution is the safe default.  OCI workloads select the container
    profile with ``RAG_CONFIG_PROFILE=container``; production generally injects
    its settings through Kubernetes environment variables, which retain the
    highest Pydantic settings priority.
    """

    profile = getenv("RAG_CONFIG_PROFILE", "host").lower()
    if profile not in {"host", "container"}:
        raise ValueError("RAG_CONFIG_PROFILE must be either 'host' or 'container'.")

    root = Path(__file__).resolve().parents[3]
    files: list[Path] = [
        root / ".env",
        root / "config" / "env" / f"{profile}.env",
    ]
    selected_worker = worker_name or getenv("RAG_WORKER_NAME")
    if selected_worker:
        if not fullmatch(r"[a-z0-9-]+", selected_worker):
            raise ValueError("RAG_WORKER_NAME must contain only lowercase letters, digits, and hyphens.")
        worker_profile = root / "config" / "workers" / f"{selected_worker}.env"
        if not worker_profile.is_file():
            raise ValueError(f"No worker configuration profile exists for '{selected_worker}'.")
        files.append(worker_profile)
    files.append(root / "secrets" / "local-runtime-secrets.env")
    return tuple(files)


@lru_cache
def get_settings(worker_name: str | None = None) -> Settings:
    """Return settings for the base profile and, when selected, one worker profile."""

    return Settings(_env_file=_environment_files(worker_name))
