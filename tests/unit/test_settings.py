from pathlib import Path

from rag_ingestion.config.settings import Settings


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
