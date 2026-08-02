from pathlib import Path

from rag_ingestion.config.settings import Settings, _environment_files


def test_postgres_dsn_is_loaded_from_secret_env_file(monkeypatch) -> None:
    repo_root = Path(__file__).resolve().parents[2]

    monkeypatch.delenv("RAG_POSTGRES_DSN", raising=False)
    monkeypatch.delenv("POSTGRES_DSN", raising=False)
    monkeypatch.delenv("postgres_dsn", raising=False)

    settings = Settings(
        _env_file=(
            repo_root / ".env",
            repo_root / "config" / "env" / "host.env",
            repo_root / "secrets" / "local-runtime-secrets.env",
        )
    )

    assert settings.postgres_dsn.startswith("postgresql+asyncpg://")


def test_document_fetcher_poll_timeout_has_a_low_volume_default(monkeypatch) -> None:
    monkeypatch.setenv("RAG_DOCUMENT_FETCHER_POLL_TIMEOUT_SECONDS", "12.5")

    settings = Settings(
        postgres_dsn="postgresql+asyncpg://user:password@localhost/rag",
        minio_access_key="access",
        minio_secret_key="secret",
        qdrant_api_key="key",
    )

    assert settings.document_fetcher_poll_timeout_seconds == 12.5


def test_document_fetcher_limits_are_configurable(monkeypatch) -> None:
    monkeypatch.setenv("RAG_DOCUMENT_FETCHER_MAX_DOCUMENT_BYTES", "10485760")

    settings = Settings(
        postgres_dsn="postgresql+asyncpg://user:password@localhost/rag",
        minio_access_key="access",
        minio_secret_key="secret",
        qdrant_api_key="key",
    )

    assert settings.document_fetcher_max_document_bytes == 10_485_760


def test_api_upload_limit_is_configurable(monkeypatch) -> None:
    monkeypatch.setenv("RAG_API_MAX_UPLOAD_BYTES", "104857600")

    settings = Settings(
        postgres_dsn="postgresql+asyncpg://user:password@localhost/rag",
        minio_access_key="access",
        minio_secret_key="secret",
        qdrant_api_key="key",
    )

    assert settings.api_max_upload_bytes == 104_857_600


def test_outbox_worker_selects_its_own_profile() -> None:
    profile_names = [path.name for path in _environment_files("outbox-publisher")]

    assert "outbox-publisher.env" in profile_names


def test_extractor_limits_concurrency_and_extends_its_kafka_processing_window(monkeypatch) -> None:
    monkeypatch.setenv("RAG_DOCUMENT_EXTRACTOR_MAX_CONCURRENCY", "2")
    monkeypatch.setenv("RAG_DOCUMENT_EXTRACTOR_MAX_POLL_INTERVAL_SECONDS", "1800")

    settings = Settings(
        postgres_dsn="postgresql+asyncpg://user:password@localhost/rag",
        minio_access_key="access",
        minio_secret_key="secret",
        qdrant_api_key="key",
    )

    assert settings.document_extractor_max_concurrency == 2
    assert settings.document_extractor_max_poll_interval_seconds == 1800
