"""Typed configuration for the pipeline's external service adapters."""

from functools import lru_cache
from os import getenv
from pathlib import Path
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

    postgres_dsn: str
    kafka_bootstrap_servers: str = "localhost:29092"
    apicurio_url: AnyHttpUrl = "http://localhost:6980"
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
    observability_mode: Literal["console", "otlp"] = "console"
    otel_exporter_otlp_endpoint: AnyHttpUrl = "http://localhost:4317"
    otel_traces_sampler: str = "parentbased_traceidratio"
    otel_traces_sampler_arg: float = Field(default=1.0, ge=0.0, le=1.0)
    # Keycloak is available locally but the ``rag`` realm is not provisioned
    # by this repository, so enable OIDC only through an explicit URL.
    oidc_issuer_url: AnyHttpUrl | None = None


def _environment_files() -> tuple[Path, Path, Path]:
    """Return the selected non-secret profile and local override files.

    Host execution is the safe default.  OCI workloads select the container
    profile with ``RAG_CONFIG_PROFILE=container``; production generally injects
    its settings through Kubernetes environment variables, which retain the
    highest Pydantic settings priority.
    """

    profile = getenv("RAG_CONFIG_PROFILE", "host").lower()
    if profile not in {"host", "container"}:
        raise ValueError("RAG_CONFIG_PROFILE must be either 'host' or 'container'.")

    root = Path(__file__).resolve().parents[3]
    return (
        root / ".env",
        root / "config" / "env" / f"{profile}.env",
        root / "secrets" / "local-runtime-secrets.env",
    )


@lru_cache
def get_settings() -> Settings:
    """Return one immutable settings instance using the selected env profile."""

    return Settings(_env_file=_environment_files())
